"""The crawl database: one SQLite file per user, holding every project and crawl.

Lives in the app data dir (not Caches — it's crawl history, and cleaners wipe caches), the way
the sibling `serp` tool keeps its journal; `SPIDER_DB_PATH` overrides it (tests, a second DB).
Schema changes go through Alembic migrations (`rb_spider/migrations`), applied automatically
when the database is opened. `metadata` below mirrors the latest migration.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import platformdirs
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy import event

from .errors import InvalidArguments
from .extract import Page
from .version import CLI_NAME

metadata = sa.MetaData()

projects = sa.Table(
    "projects",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("name", sa.String, nullable=False, unique=True),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
)
crawls = sa.Table(
    "crawls",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True),
    sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    sa.Column("start_url", sa.String, nullable=False),
    sa.Column("status", sa.String, nullable=False),  # running | finished | failed | interrupted
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Column("pages", sa.Integer, nullable=False, server_default="0"),
)
pages = sa.Table(
    "pages",
    metadata,
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("url", sa.String, primary_key=True),
    sa.Column("status_code", sa.Integer, nullable=False),
    sa.Column("redirect_url", sa.String),
    sa.Column("content_type", sa.String),
    sa.Column("title", sa.String),
    sa.Column("bytes", sa.Integer, nullable=False),
    sa.Column("depth", sa.Integer, nullable=False),
    sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("error", sa.String),  # why there is no response (status_code 0)
    sa.Column("blocked", sa.String),  # "robots_txt": not fetched on purpose (status_code 0)
    sa.Column("refresh_url", sa.String),  # target of a meta / HTTP Refresh
    sa.Column("refresh_kind", sa.String),  # "meta" | "http"
)
issues = sa.Table(
    "issues",
    metadata,
    sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
    sa.Column("code", sa.String, nullable=False),
    sa.Column("url", sa.String, nullable=False),
    sa.Column("detail", sa.String),
    sa.Index("issues_by_code", "crawl_id", "code"),
)


def db_path() -> Path:
    """`SPIDER_DB_PATH`, else `<app data dir>/spider/spider.sqlite` (~/Library/Application Support on macOS)."""
    explicit = os.environ.get(f"{CLI_NAME.upper()}_DB_PATH")
    if explicit:
        return Path(explicit)
    return Path(platformdirs.user_data_dir(CLI_NAME, appauthor=False)) / f"{CLI_NAME}.sqlite"


def _pragmas(dbapi_connection, _record) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")  # readers (`spider status`) never block the writing crawl
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def open_db(path: Path | None = None) -> sa.Engine:
    """Open (creating if needed) the crawl database and bring its schema up to date."""
    path = path or db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = sa.create_engine(f"sqlite:///{path}")
    event.listen(engine, "connect", _pragmas)
    config = Config()
    config.set_main_option("script_location", "rb_spider:migrations")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    return engine


@contextmanager
def database(path: Path | None = None) -> Iterator[sa.Engine]:
    """`open_db` for one command: the engine's connections are closed on exit."""
    engine = open_db(path)
    try:
        yield engine
    finally:
        engine.dispose()


def _now() -> datetime:
    return datetime.now(UTC)


def start_crawl(engine: sa.Engine, project: str, start_url: str) -> int:
    """Register a running crawl (creating the project on first use) and return its id."""
    with engine.begin() as conn:
        project_id = conn.execute(sa.select(projects.c.id).where(projects.c.name == project)).scalar()
        if project_id is None:
            insert_project = sa.insert(projects).values(name=project, created_at=_now()).returning(projects.c.id)
            project_id = conn.execute(insert_project).scalar_one()
        insert_crawl = (
            sa.insert(crawls)
            .values(project_id=project_id, start_url=start_url, status="running", started_at=_now())
            .returning(crawls.c.id)
        )
        return conn.execute(insert_crawl).scalar_one()


def finish_crawl(engine: sa.Engine, crawl_id: int, status: str) -> int:
    """Close a crawl with its final status; returns the number of pages stored."""
    with engine.begin() as conn:
        count = conn.execute(sa.select(sa.func.count()).where(pages.c.crawl_id == crawl_id)).scalar_one()
        conn.execute(
            sa.update(crawls).where(crawls.c.id == crawl_id).values(status=status, finished_at=_now(), pages=count)
        )
        return count


class PageWriter:
    """Buffers pages and writes them in batches: memory stays flat however big the site is."""

    def __init__(self, engine: sa.Engine, crawl_id: int, batch_size: int = 500) -> None:
        self.engine, self.crawl_id, self.batch_size = engine, crawl_id, batch_size
        self._rows: list[dict] = []
        self.written = 0

    @property
    def count(self) -> int:
        """Pages handed to the writer so far, flushed or not."""
        return self.written + len(self._rows)

    def add(self, page: Page, depth: int) -> None:
        self._rows.append(
            {
                "crawl_id": self.crawl_id,
                "url": page.url,
                "status_code": page.status_code,
                "redirect_url": page.redirect_url,
                "content_type": page.content_type,
                "title": page.title,
                "bytes": page.bytes,
                "depth": depth,
                "fetched_at": _now(),
                "error": page.error,
                "blocked": page.blocked,
                "refresh_url": page.refresh_url,
                "refresh_kind": page.refresh_kind,
            }
        )
        if len(self._rows) >= self.batch_size:
            self.flush()

    def flush(self) -> None:
        if not self._rows:
            return
        with self.engine.begin() as conn:
            # A URL reached twice keeps its latest response. SQLite syntax; remote DBs (v2) need an upsert.
            conn.execute(sa.insert(pages).prefix_with("OR REPLACE"), self._rows)
        self.written += len(self._rows)
        self._rows = []


@dataclass
class CrawlRow:
    id: int
    project: str
    start_url: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    pages: int


def list_crawls(engine: sa.Engine, limit: int | None = None) -> list[CrawlRow]:
    """Crawls of every project, newest first."""
    query = (
        sa.select(
            crawls.c.id,
            projects.c.name,
            crawls.c.start_url,
            crawls.c.status,
            crawls.c.started_at,
            crawls.c.finished_at,
            crawls.c.pages,
        )
        .join(projects, projects.c.id == crawls.c.project_id)
        .order_by(crawls.c.id.desc())
        .limit(limit)
    )
    with engine.connect() as conn:
        rows = [CrawlRow(*row) for row in conn.execute(query)]
    for row in rows:  # SQLite drops the timezone; everything is written in UTC
        row.started_at = row.started_at.replace(tzinfo=UTC)
        row.finished_at = row.finished_at.replace(tzinfo=UTC) if row.finished_at else None
    return rows


def resolve_crawl_id(engine: sa.Engine, crawl_id: int | None) -> int:
    """The given crawl if it exists, else (None) the newest one — what analysis commands default to."""
    with engine.connect() as conn:
        if crawl_id is None:
            latest = conn.execute(sa.select(sa.func.max(crawls.c.id))).scalar()
            if latest is None:
                raise InvalidArguments(f"No crawls yet — run '{CLI_NAME} crawl <url>' first.")
            return latest
        if conn.execute(sa.select(crawls.c.id).where(crawls.c.id == crawl_id)).scalar() is None:
            raise InvalidArguments(f"No crawl #{crawl_id} — see '{CLI_NAME} crawls list'.")
        return crawl_id
