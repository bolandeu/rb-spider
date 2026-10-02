"""The crawl database: every project and crawl — a local SQLite file, or the shared PostgreSQL (`SPIDER_DATABASE_URL`).

Opening, migrations and the dialect bridge are `core/db.py`; the tables are `core/tables.py` (re-exported here,
`storage.pages` & co. are what the rest of the code uses). This module adds the writer and the crawl bookkeeping.
"""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

import sqlalchemy as sa
import zstandard
from rb_keys import norm_domain, norm_url

from . import db
from .errors import InvalidArguments
from .extract import Page
from .scope import LINK_FIELDS
from .tables import (  # noqa: F401 — re-exported: storage.<table> is what callers use
    LINK_DATA,
    crawls,
    custom_values,
    frontier,
    issues,
    lighthouse_audits,
    link_rows,
    links,
    metadata,
    near_duplicates,
    pages,
    projects,
    render_events,
    rendered_images,
    sitemap_files,
    sitemap_urls,
    url_metrics,
    urls,
)
from .version import CLI_NAME


def db_path() -> Path:
    """`SPIDER_DB_PATH`, else `<app data dir>/spider/spider.sqlite` (~/Library/Application Support on macOS)."""
    return db.sqlite_path()


def db_url() -> str | None:
    """`SPIDER_DATABASE_URL` (or the legacy `SPIDER_DB_URL`) — the shared PostgreSQL instead of the local file."""
    return db.database_url()


def html_db_path() -> Path:
    """Stored HTML (`crawl.store_html`) lives beside the crawl database, not in it: the main DB stays small. With
    SPIDER_DATABASE_URL it's a local file too, one per remote database (named after it)."""
    main = db_path()
    if url := db_url():
        name = sa.make_url(url).database or "remote"
        return main.with_name(f"{main.stem}-html-{name}{main.suffix}")
    return main.with_name(f"{main.stem}-html{main.suffix}")


def screenshots_dir(crawl_id: int) -> Path:
    """A crawl's screenshots (crawl.render_screenshots): JPEG files in a folder beside the stored HTML."""
    html = html_db_path()
    return html.with_name(html.stem.replace("-html", "-screenshots", 1)) / str(crawl_id)


html_metadata = sa.MetaData()
html_pages = sa.Table(
    "html",
    html_metadata,
    sa.Column("crawl_id", sa.Integer, primary_key=True),
    sa.Column("url", sa.String, primary_key=True),
    sa.Column("body", sa.LargeBinary, nullable=False),  # zstd-compressed response body
    sa.Column("rendered", sa.LargeBinary),  # zstd-compressed DOM after JavaScript (crawl.render), for View Source
)


def open_html_db(path: Path) -> sa.Engine:
    """The stored-HTML file, created or brought up to date (files from before View Source lack `rendered`)."""
    engine = sa.create_engine(f"sqlite:///{path}")
    html_metadata.create_all(engine)
    with engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(html)")}
        if "rendered" not in columns:
            conn.exec_driver_sql("ALTER TABLE html ADD COLUMN rendered BLOB")
    return engine


def open_db(path: Path | None = None, *, migrate: bool = True) -> sa.Engine:
    """Open the crawl database: an explicit SQLite `path`, else `SPIDER_DATABASE_URL`, else the local file.

    SQLite is created and migrated on open; PostgreSQL only checked against this release's schema (`spider db
    upgrade` migrates it). `migrate=False` leaves it as it is — for `spider db info|upgrade`, which report it.
    """
    if path is None and (url := db_url()) is not None:
        engine = db.postgres_engine(url)
        if migrate:
            try:
                db.check_schema(engine)
            except Exception:
                engine.dispose()
                raise
        return engine
    engine = db.sqlite_engine(path or db_path())
    if migrate:
        db.upgrade(engine)
    return engine


NO_LIMIT = 2**62  # `LIMIT :limit` without a limit: SQLite's -1 is an error in PostgreSQL, NULL one in SQLite


def insert_or_replace(conn: sa.Connection, table: sa.Table) -> sa.Insert:
    """INSERT that replaces a row with the same natural key — the table's UNIQUE constraint (SQLite's INSERT OR
    REPLACE); the surrogate `id` is the database's."""
    if is_sqlite(conn):
        return sa.insert(table).prefix_with("OR REPLACE")
    from sqlalchemy.dialects.postgresql import insert

    statement = insert(table)
    [unique] = [c for c in table.constraints if isinstance(c, sa.UniqueConstraint)]
    keys = [column.name for column in unique.columns]
    return statement.on_conflict_do_update(
        index_elements=keys,
        set_={c.name: statement.excluded[c.name] for c in table.columns if c.name not in (*keys, "id")},
    )


def is_sqlite(bind: sa.Engine | sa.Connection) -> bool:
    return bind.dialect.name == "sqlite"


@dataclass(frozen=True)
class _Streamed:
    conn: sa.Connection
    rows: int

    def execute(self, statement, parameters=None) -> sa.CursorResult:
        return self.conn.execute(statement, parameters, execution_options={"yield_per": self.rows})


def streamed(conn: sa.Connection, rows: int) -> _Streamed:
    """`streamed(conn, 1000).execute(query)` — the result read `rows` at a time. Not conn.execution_options(): that
    changes the connection itself, and in PostgreSQL every later statement on it would go through a server cursor."""
    return _Streamed(conn, rows)


@contextmanager
def database(path: Path | None = None, *, migrate: bool = True) -> Iterator[sa.Engine]:
    """`open_db` for one command: the engine's connections are closed on exit."""
    engine = open_db(path, migrate=migrate)
    try:
        yield engine
    finally:
        engine.dispose()


def _now() -> datetime:
    return datetime.now(UTC)


def start_crawl(engine: sa.Engine, project: str, start_url: str, settings: dict | None = None) -> int:
    """Register a running crawl (creating the project on first use) and return its id."""
    with engine.begin() as conn:
        project_id = conn.execute(sa.select(projects.c.id).where(projects.c.name == project)).scalar()
        if project_id is None:
            insert_project = sa.insert(projects).values(name=project, created_at=_now()).returning(projects.c.id)
            project_id = conn.execute(insert_project).scalar_one()
        insert_crawl = (
            sa.insert(crawls)
            .values(project_id=project_id, start_url=start_url, status="running", started_at=_now(), settings=settings)
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


_PAGE_COLUMNS = [column.name for column in pages.columns if column.name != "id"]  # the database numbers rows
_URL_COLUMNS = ["crawl_id", "url", "url_key", "domain_key"]


def _key(normalize, url: str) -> str | None:
    try:
        return normalize(url)
    except ValueError:  # not a web URL (mailto:, malformed): no key — an empty one would join every bad URL
        return None


# A site's navigation links come back in every batch: their keys are worked out once (bounded — memory stays flat).
@lru_cache(maxsize=65536)
def url_keys(url: str) -> tuple[str | None, str | None]:
    """`url_key`, `domain_key` of a URL — the shared keys (rb-keys) other tools and Directus join pages by."""
    return _key(norm_url, url), _key(norm_domain, url)


_LINK_COLUMNS = ["crawl_id", *LINK_FIELDS]


def _pg_value(table: sa.Table, name: str, i: int) -> str:
    """Element `i` of a JSON row as the column's PostgreSQL type (JSON gives text)."""
    kind = table.c[name].type
    text = f"(value->>{i})"
    if isinstance(kind, sa.Boolean):
        return f"{text}::boolean"
    if isinstance(kind, sa.Integer):
        return f"{text}::bigint"
    if isinstance(kind, sa.Float):
        return f"{text}::double precision"
    if isinstance(kind, sa.DateTime):
        return f"{text}::timestamp AT TIME ZONE 'UTC'"  # _timestamp(): UTC without an offset
    return text


def _insert_json(table: sa.Table, columns: list[str], dialect: str, verb: str = "INSERT", conflict: str = "") -> str:
    """Insert rows passed as one JSON array of arrays: the database runs the whole batch in one step, without
    Python's GIL — `executemany` takes the GIL back after every row, and with the crawl's event loop busy on the
    same GIL that made writing three times slower. SQLite reads it with `json_each`, PostgreSQL with
    `json_array_elements`; `verb` / `conflict` — SQLite's INSERT OR … / PostgreSQL's ON CONFLICT."""
    names = ", ".join(columns)
    if dialect == "sqlite":
        values = ", ".join(f"json_extract(value, '$[{i}]')" for i in range(len(columns)))
        return f"{verb} INTO {table.name} ({names}) SELECT {values} FROM json_each(?)"  # noqa: S608 — fixed names
    values = ", ".join(_pg_value(table, name, i) for i, name in enumerate(columns))
    return f"INSERT INTO {table.name} ({names}) SELECT {values} FROM json_array_elements(%s::json) AS value {conflict}"  # noqa: S608


_JSON_CHUNK = 5000  # rows per statement: a bounded JSON argument keeps the database's memory flat


@dataclass(frozen=True)
class _WriterSql:
    """The writer's statements for one database dialect."""

    pages: str
    link_urls: str
    link_rows: str
    custom: str
    events: str
    images: str
    sitemap_urls: str
    queued: str
    mark_done: str


def _writer_sql(dialect: str) -> _WriterSql:
    sqlite = dialect == "sqlite"
    link_types = {"crawl_id": link_rows.c.crawl_id, "source": urls.c.url, "target": urls.c.url,
                  **{name: link_rows.c[name] for name in LINK_DATA}}  # fmt: skip
    if sqlite:
        link_json = ", ".join(f"json_extract(value, '$[{i}]') AS {name}" for i, name in enumerate(_LINK_COLUMNS))
        rows_source, ignore, no_conflict = "json_each(?)", "INSERT OR IGNORE", ""
    else:
        link_json = ", ".join(
            f"{_pg_value(link_types[name].table, link_types[name].name, i)} AS {name}"
            for i, name in enumerate(_LINK_COLUMNS)
        )
        rows_source, ignore, no_conflict = "json_array_elements(%s::json) AS value", "INSERT", " ON CONFLICT DO NOTHING"
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in _PAGE_COLUMNS if c not in ("crawl_id", "url"))
    return _WriterSql(
        # a URL reached twice keeps its latest response
        pages=_insert_json(pages, _PAGE_COLUMNS, dialect, "INSERT OR REPLACE",
                           f"ON CONFLICT (crawl_id, url) DO UPDATE SET {updates}"),
        # A batch of links: its URLs get ids (new ones inserted), then the rows go in with the ids — looked up inside
        # the database, so the writer keeps no URL -> id map in memory.
        # The URLs come distinct and keyed from the writer (`_link_urls`): the keys are Python's (rb-keys).
        link_urls=_insert_json(urls, _URL_COLUMNS, dialect, ignore, no_conflict),
        # The ids by a lookup per row through the unique index — not a JOIN: with planner statistics from earlier,
        # smaller crawls in the same database SQLite could pick a scan of `urls` per row (4 pages then a full one: 20 s).
        link_rows=(
            f"WITH r AS (SELECT {link_json} FROM {rows_source}) "  # noqa: S608 — fixed names
            f"INSERT INTO spider_link_rows (crawl_id, source_id, target_id, {', '.join(LINK_DATA)}) "
            "SELECT r.crawl_id, (SELECT id FROM spider_urls WHERE url = r.source AND crawl_id = r.crawl_id),"
            " (SELECT id FROM spider_urls WHERE url = r.target AND crawl_id = r.crawl_id),"
            f" {', '.join(f'r.{c}' for c in LINK_DATA)} FROM r"
        ),
        custom=_insert_json(custom_values, ["crawl_id", "url", "kind", "name", "value", "n"], dialect),
        events=_insert_json(render_events, ["crawl_id", "url", "kind", "message", "resource"], dialect),
        images=_insert_json(rendered_images, ["crawl_id", "url", "image", "real_width", "real_height", "display_width",
                                              "display_height"], dialect),
        sitemap_urls=_insert_json(sitemap_urls, ["crawl_id", "url", "source", "lastmod"], dialect),
        queued=_insert_json(frontier, ["crawl_id", "url", "depth", "check_only"], dialect, "INSERT OR IGNORE",
                            "ON CONFLICT DO NOTHING"),
        mark_done=(
            "UPDATE spider_frontier SET done = TRUE WHERE crawl_id = ? AND url IN (SELECT value FROM json_each(?))"
            if sqlite
            else "UPDATE spider_frontier SET done = TRUE WHERE crawl_id = %s AND url IN (SELECT json_array_elements_text(%s::json))"
        ),
    )  # fmt: skip


_WRITER_SQL = {name: _writer_sql(name) for name in ("sqlite", "postgresql")}


def _timestamp() -> str:
    """`_now()` as SQLAlchemy stores a DateTime in SQLite — the writer bypasses SQLAlchemy's types."""
    return _now().strftime("%Y-%m-%d %H:%M:%S.%f")


@dataclass
class _Batch:
    custom: list[tuple] = field(default_factory=list)
    events: list[tuple] = field(default_factory=list)
    images: list[tuple] = field(default_factory=list)
    sitemap_files: list[dict] = field(default_factory=list)
    sitemap_urls: list[tuple] = field(default_factory=list)
    pages: list[tuple] = field(default_factory=list)
    links: list[tuple] = field(default_factory=list)
    queued: list[tuple] = field(default_factory=list)
    done: list[str] = field(default_factory=list)
    html: list[dict] = field(default_factory=list)


class PageWriter:
    """Buffers pages, links and queue entries and writes them in one transaction per batch.

    A batch goes out every `batch_size` pages or `flush_every_s` seconds, whichever comes first — memory
    stays flat however big the site is, and `spider status` sees progress while the crawl runs. One
    transaction for everything is what makes resume lossless (see `frontier`). With `store_html`,
    response bodies go zstd-compressed to the separate HTML database.

    Batches are written by a thread of their own (SQLite works without holding the GIL, so the crawl
    goes on meanwhile), one at a time: a new batch waits for the previous one, so a slow disk slows the
    crawl down instead of piling batches up in memory. Rows are plain tuples, sent to SQLite as JSON
    (`_insert_json`) — at ~80 links a page, SQLAlchemy's per-row work cost more than SQLite's.
    """

    def __init__(
        self,
        engine: sa.Engine,
        crawl_id: int,
        batch_size: int = 500,
        *,
        store_html: bool = False,
        flush_every_s: float = 2.0,
    ) -> None:
        self.engine, self.crawl_id, self.batch_size, self.flush_every_s = engine, crawl_id, batch_size, flush_every_s
        self._batch = _Batch()
        self._thread = ThreadPoolExecutor(1, thread_name_prefix="spider-writer")
        self._writing: Future | None = None
        # The first failed write. It surfaces in whatever handler hands the writer the next page — and Crawlee takes an
        # exception there for that request's error and goes on: the crawl must check this and stop (crawl._run), and
        # nothing more is written — a lost batch (its queue entries, pages, `done` marks) would leave the rest orphaned.
        self.failed: BaseException | None = None
        self._last_flush = time.monotonic()
        self.count = 0  # pages handed to the writer so far, written or not
        self.html_engine: sa.Engine | None = None
        if store_html:
            path = html_db_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            self.html_engine = open_html_db(path)
            self._compressor = zstandard.ZstdCompressor(level=3)

    def queued(self, url: str, depth: int, check_only: bool) -> None:
        """A URL went into the crawl queue."""
        self._batch.queued.append((self.crawl_id, url, depth, check_only))

    def add(self, page: Page, depth: int, body: bytes | None = None, rendered: bytes | None = None) -> None:
        """A URL's result: stored with its queue entry marked done, in the same batch. With store_html the body is
        kept too, and a rendered page's DOM beside it."""
        if self.html_engine is not None and body:
            self._batch.html.append(
                {
                    "crawl_id": self.crawl_id,
                    "url": page.url,
                    "body": self._compressor.compress(body),
                    "rendered": self._compressor.compress(rendered) if rendered else None,
                }
            )
        # Every row carries every column: a batch insert needs one shape, and a redirect or an
        # error page has no on-page fields at all.
        row = page.onpage | {
            "crawl_id": self.crawl_id,
            "url": page.url,
            "status_code": page.status_code,
            "redirect_url": page.redirect_url,
            "content_type": page.content_type,
            "title": page.title,
            "bytes": page.bytes,
            "depth": depth,
            "fetched_at": _timestamp(),
            "error": page.error,
            "blocked": page.blocked,
            "refresh_url": page.refresh_url,
            "refresh_kind": page.refresh_kind,
        }
        row["url_key"], row["domain_key"] = url_keys(page.url)
        self._batch.pages.append(tuple(row.get(column) for column in _PAGE_COLUMNS))
        self._batch.custom.extend((self.crawl_id, page.url, *values) for values in page.custom)
        self._batch.events.extend((self.crawl_id, page.url, *values) for values in page.events)
        self._batch.images.extend((self.crawl_id, page.url, *values) for values in page.images)
        self._batch.done.append(page.url)
        self.count += 1
        if len(self._batch.pages) >= self.batch_size or time.monotonic() - self._last_flush >= self.flush_every_s:
            self.flush(wait=False)

    def add_links(self, rows: list[tuple]) -> None:
        """`links` rows for this crawl, in `scope.LINK_FIELDS` order."""
        crawl_id = (self.crawl_id,)
        self._batch.links.extend(crawl_id + row for row in rows)

    def sitemap(self, file: dict, entries: list[tuple[str, str | None]]) -> None:
        """A sitemap file (sitemap_files columns) and its entries (url, lastmod), written with the next batch."""
        self._batch.sitemap_files.append({"crawl_id": self.crawl_id, **file})
        self._batch.sitemap_urls.extend((self.crawl_id, url, file["url"], lastmod) for url, lastmod in entries)

    def flush(self, *, wait: bool = True) -> None:
        """Hand the buffered rows to the writer thread; `wait` — return once everything is on disk."""
        if self.failed is not None:
            raise self.failed
        self._last_flush = time.monotonic()
        batch, self._batch = self._batch, _Batch()
        self._wait()
        if batch.pages or batch.links or batch.queued or batch.html or batch.sitemap_files:
            self._writing = self._thread.submit(self._write, batch)
        if wait:
            self._wait()

    def close(self) -> None:
        """Write what's left and stop the writer thread (nothing more after a failed write: the crawl reports it)."""
        try:
            if self.failed is None:
                self.flush()
        finally:
            self._thread.shutdown()
            if self.html_engine is not None:
                self.html_engine.dispose()

    def _wait(self) -> None:
        if self._writing is not None:
            writing, self._writing = self._writing, None
            try:
                writing.result()  # a failed write surfaces here, in the crawl
            except Exception as exc:
                self.failed = exc
                raise

    def _link_urls(self, links: list[tuple]) -> list[tuple]:
        """`urls` rows for every URL a batch of links refers to, once each, with their keys."""
        found = dict.fromkeys(url for row in links for url in row[1:3])  # (crawl_id, source, target, …)
        return [(self.crawl_id, url, *url_keys(url)) for url in found]

    def _write(self, batch: _Batch) -> None:
        if batch.html and self.html_engine is not None:  # a separate file: stored first, harmless if orphaned
            with self.html_engine.begin() as conn:
                conn.execute(sa.insert(html_pages).prefix_with("OR REPLACE"), batch.html)
        sql = _WRITER_SQL[self.engine.dialect.name]
        with self.engine.begin() as conn:
            for statement, rows in (
                (sql.queued, batch.queued),
                (sql.pages, batch.pages),
                (sql.link_urls, self._link_urls(batch.links)),  # before the links: they refer to the URLs' ids
                (sql.link_rows, batch.links),
            ):
                for chunk in range(0, len(rows), _JSON_CHUNK):  # SQLite parses a JSON argument whole
                    conn.exec_driver_sql(
                        statement, (json.dumps(rows[chunk : chunk + _JSON_CHUNK], ensure_ascii=False),)
                    )
            for rows, statement in ((batch.custom, sql.custom), (batch.events, sql.events), (batch.images, sql.images)):
                for chunk in range(0, len(rows), _JSON_CHUNK):
                    conn.exec_driver_sql(
                        statement, (json.dumps(rows[chunk : chunk + _JSON_CHUNK], ensure_ascii=False),)
                    )
            if batch.sitemap_files:
                conn.execute(sa.insert(sitemap_files), batch.sitemap_files)
            for chunk in range(0, len(batch.sitemap_urls), _JSON_CHUNK):
                data = json.dumps(batch.sitemap_urls[chunk : chunk + _JSON_CHUNK], ensure_ascii=False)
                conn.exec_driver_sql(sql.sitemap_urls, (data,))
            if batch.done:
                conn.exec_driver_sql(sql.mark_done, (self.crawl_id, json.dumps(batch.done, ensure_ascii=False)))


def enqueue(engine: sa.Engine, crawl_id: int, urls: list[str], depth: int = 0) -> None:
    """Put URLs into a crawl's queue before it runs (list mode)."""
    rows = [(crawl_id, url, depth, False) for url in urls]
    with engine.begin() as conn:
        for chunk in range(0, len(rows), _JSON_CHUNK):
            conn.exec_driver_sql(_WRITER_SQL[engine.dialect.name].queued,
                                 (json.dumps(rows[chunk : chunk + _JSON_CHUNK], ensure_ascii=False),))  # fmt: skip


def reset_for_respider(engine: sa.Engine, crawl_id: int, targets: list[str]) -> list[str]:
    """Put a crawl's URLs back in its queue with their outgoing links and custom values removed (the page rows are
    replaced when fetched). Nothing changes if any URL isn't in the crawl — the unknown ones are returned."""
    with engine.begin() as conn:
        known = set(conn.execute(sa.select(frontier.c.url).where(frontier.c.crawl_id == crawl_id,
                                                                  frontier.c.url.in_(targets))).scalars())  # fmt: skip
        missing = [url for url in targets if url not in known]
        if missing:
            return missing
        ids = sa.select(urls.c.id).where(urls.c.crawl_id == crawl_id, urls.c.url.in_(targets))
        conn.execute(sa.delete(link_rows).where(link_rows.c.crawl_id == crawl_id, link_rows.c.source_id.in_(ids)))
        conn.execute(
            sa.delete(custom_values).where(custom_values.c.crawl_id == crawl_id, custom_values.c.url.in_(targets))
        )
        conn.execute(
            sa.delete(rendered_images).where(rendered_images.c.crawl_id == crawl_id, rendered_images.c.url.in_(targets))
        )
        conn.execute(
            sa.delete(render_events).where(render_events.c.crawl_id == crawl_id, render_events.c.url.in_(targets))
        )
        conn.execute(sa.update(frontier).where(frontier.c.crawl_id == crawl_id, frontier.c.url.in_(targets))
                     .values(done=False))  # fmt: skip
    return []


def crawl_pid(engine: sa.Engine, crawl_id: int) -> int | None:
    with engine.connect() as conn:
        return conn.execute(sa.select(crawls.c.pid).where(crawls.c.id == crawl_id)).scalar()


def set_pid(engine: sa.Engine, crawl_id: int, pid: int | None) -> None:
    with engine.begin() as conn:
        conn.execute(sa.update(crawls).where(crawls.c.id == crawl_id).values(pid=pid, status="running"))


@dataclass
class Frontier:
    seen: dict[str, int]  # every queued URL -> depth
    pending: list[tuple[str, int, bool]]  # (url, depth, check_only) not done yet


def load_frontier(engine: sa.Engine, crawl_id: int) -> Frontier:
    """The queue a crawl left behind: what it has seen, and what it still has to fetch."""
    query = sa.select(frontier.c.url, frontier.c.depth, frontier.c.check_only, frontier.c.done).where(
        frontier.c.crawl_id == crawl_id
    )
    seen: dict[str, int] = {}
    pending: list[tuple[str, int, bool]] = []
    with engine.connect() as conn:
        for url, depth, check_only, done in conn.execute(query):
            seen[url] = depth
            if not done:
                pending.append((url, depth, check_only))
    return Frontier(seen, pending)


@dataclass
class Progress:
    pages: int  # stored so far
    pending: int  # queued, not fetched yet


def progress(engine: sa.Engine, crawl_id: int) -> Progress:
    with engine.connect() as conn:
        stored = conn.execute(sa.select(sa.func.count()).where(pages.c.crawl_id == crawl_id)).scalar_one()
        pending = conn.execute(
            sa.select(sa.func.count()).where(frontier.c.crawl_id == crawl_id, sa.not_(frontier.c.done))
        ).scalar_one()
    return Progress(stored, pending)


@dataclass
class CrawlRow:
    id: int
    project: str
    start_url: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    pages: int


def get_crawl(engine: sa.Engine, crawl_id: int) -> tuple[CrawlRow, dict | None]:
    """One crawl and the settings snapshot it ran with (None for crawls made before snapshots)."""
    query = (
        sa.select(
            crawls.c.id,
            projects.c.name,
            crawls.c.start_url,
            crawls.c.status,
            crawls.c.started_at,
            crawls.c.finished_at,
            crawls.c.pages,
            crawls.c.settings,
        )
        .join(projects, projects.c.id == crawls.c.project_id)
        .where(crawls.c.id == crawl_id)
    )
    with engine.connect() as conn:
        *fields, snapshot = conn.execute(query).one()
    row = CrawlRow(*fields)
    row.started_at = row.started_at.replace(tzinfo=UTC)
    row.finished_at = row.finished_at.replace(tzinfo=UTC) if row.finished_at else None
    return row, snapshot


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


def get_html(crawl_id: int, url: str, *, rendered: bool = False) -> bytes | None:
    """A stored response body (crawl made with `crawl.store_html`), or with `rendered` its DOM after JavaScript;
    None — not stored."""
    path = html_db_path()
    if not path.is_file():
        return None
    engine = open_html_db(path)
    try:
        with engine.connect() as conn:
            where = sa.and_(html_pages.c.crawl_id == crawl_id, html_pages.c.url == url)
            column = html_pages.c.rendered if rendered else html_pages.c.body
            blob = conn.execute(sa.select(column).where(where)).scalar()
    finally:
        engine.dispose()
    return zstandard.ZstdDecompressor().decompress(blob) if blob is not None else None


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


def links_of(
    engine: sa.Engine, crawl_id: int, url: str, direction: str = "out", limit: int | None = None
) -> tuple[int, list[dict]]:
    """Links from (`out`) or to (`in`) a URL, with the response code of the URL at the other end."""
    mine, other = (links.c.source, links.c.target) if direction == "out" else (links.c.target, links.c.source)
    where = sa.and_(links.c.crawl_id == crawl_id, mine == url)
    query = (
        sa.select(
            links.c.source,
            links.c.target,
            links.c.kind,
            links.c.anchor,
            links.c.alt,
            links.c.rel,
            links.c.nofollow,
            links.c.internal,
            links.c.position,
            links.c.path,
            pages.c.status_code,
        )
        .select_from(links.outerjoin(pages, sa.and_(pages.c.crawl_id == links.c.crawl_id, pages.c.url == other)))
        .where(where)
        .order_by(other)
        .limit(limit)
    )
    with engine.connect() as conn:
        total = conn.execute(sa.select(sa.func.count()).select_from(links).where(where)).scalar_one()
        return total, [dict(row) for row in conn.execute(query).mappings()]
