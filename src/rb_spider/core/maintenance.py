"""Keeping the crawl database in check: deleting crawls and projects, pruning old crawls, schema, VACUUM.

The database only grows — a 100k-URL crawl takes ~800 MB — so old crawls have to go somewhere.
Deleting frees pages inside the file for the next crawls; only `vacuum` gives the space back to the
disk. Selection (`select_*`) is separate from deletion, so `--dry-run` shows exactly what would go.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import sqlalchemy as sa
from alembic.script import ScriptDirectory

from . import db, storage
from .errors import DatabaseTooNew, InvalidArguments
from .storage import crawls, projects

# Child tables of a crawl, deleted explicitly by crawl_id: faster than SQLite's per-row cascade on
# millions of link rows (the cascade stays as a safety net).
_CRAWL_TABLES = (storage.link_rows, storage.urls, storage.issues, storage.frontier, storage.url_metrics,
                 storage.near_duplicates, storage.sitemap_files, storage.sitemap_urls, storage.custom_values,
                 storage.render_events, storage.rendered_images, storage.pages)  # fmt: skip
_DURATION = re.compile(r"^\s*(\d+)\s*([hdwy])\s*$")
_UNITS = {"h": timedelta(hours=1), "d": timedelta(days=1), "w": timedelta(weeks=1), "y": timedelta(days=365)}


def parse_age(value: str) -> timedelta:
    """ "90d" / "12h" / "2w" / "1y" -> timedelta."""
    match = _DURATION.match(value)
    if not match:
        raise InvalidArguments(f"Age must look like 90d, 12h, 2w or 1y, got '{value}'.")
    return int(match.group(1)) * _UNITS[match.group(2)]


def _running(engine: sa.Engine, rows: list[storage.CrawlRow]) -> list[int]:
    from .crawl import process_alive

    def busy(row: storage.CrawlRow) -> bool:
        # no pid: a crawl registered but never started, or made before pids were kept — nothing runs it;
        # a pid we can't check (Windows) counts as running
        pid = storage.crawl_pid(engine, row.id)
        return row.status == "running" and pid is not None and process_alive(pid) is not False

    return [r.id for r in rows if busy(r)]


def select_crawls(engine: sa.Engine, crawl_ids: list[int]) -> list[storage.CrawlRow]:
    """The given crawls; an unknown id is an error, not a silent no-op."""
    rows = {r.id: r for r in storage.list_crawls(engine)}
    missing = [i for i in crawl_ids if i not in rows]
    if missing:
        raise InvalidArguments(f"No crawl #{', #'.join(map(str, missing))} — see 'spider crawls list'.")
    return [rows[i] for i in dict.fromkeys(crawl_ids)]


def select_prune(
    engine: sa.Engine, *, keep_last: int | None, older_than: timedelta | None, project: str | None = None
) -> list[storage.CrawlRow]:
    """Crawls to prune: beyond the last `keep_last` of each project and/or started more than `older_than` ago.

    With both, a crawl goes only if it is old *and* not among its project's last N.
    """
    if keep_last is None and older_than is None:
        raise InvalidArguments("Say what to prune: --keep-last N, --older-than AGE, or both.")
    if project is not None and project not in {p["name"] for p in list_projects(engine)}:
        raise InvalidArguments(f"No project '{project}' — see 'spider projects list'.")
    cutoff = datetime.now(UTC) - older_than if older_than is not None else None
    seen: dict[str, int] = {}
    doomed = []
    for row in storage.list_crawls(engine):  # newest first
        if project is not None and row.project != project:
            continue
        seen[row.project] = seen.get(row.project, 0) + 1
        beyond = keep_last is None or seen[row.project] > keep_last
        old = cutoff is None or row.started_at < cutoff
        if beyond and old:
            doomed.append(row)
    return doomed


def delete_crawls(engine: sa.Engine, rows: list[storage.CrawlRow]) -> int:
    """Delete crawls with all their data (and their stored HTML); returns how many pages went with them."""
    busy = _running(engine, rows)
    if busy:
        raise InvalidArguments(f"Crawl #{', #'.join(map(str, busy))} is still running — stop it first.")
    ids = [r.id for r in rows]
    if not ids:
        return 0
    with engine.begin() as conn:
        for table in _CRAWL_TABLES:
            conn.execute(sa.delete(table).where(table.c.crawl_id.in_(ids)))
        conn.execute(sa.delete(crawls).where(crawls.c.id.in_(ids)))
    html = storage.html_db_path()
    if html.is_file():
        html_engine = sa.create_engine(f"sqlite:///{html}")
        try:
            with html_engine.begin() as conn:
                conn.execute(sa.delete(storage.html_pages).where(storage.html_pages.c.crawl_id.in_(ids)))
        finally:
            html_engine.dispose()
    for crawl_id in ids:  # crawl.render_screenshots
        shutil.rmtree(storage.screenshots_dir(crawl_id), ignore_errors=True)
    return sum(r.pages for r in rows)


def list_projects(engine: sa.Engine) -> list[dict]:
    """Projects with their number of crawls, pages in them and the last crawl's date."""
    query = (
        sa.select(
            projects.c.name,
            sa.func.count(crawls.c.id),
            sa.func.coalesce(sa.func.sum(crawls.c.pages), 0),
            sa.func.max(crawls.c.started_at),
        )
        .select_from(projects.outerjoin(crawls, crawls.c.project_id == projects.c.id))
        .group_by(projects.c.id)
        .order_by(projects.c.name)
    )
    with engine.connect() as conn:
        rows = conn.execute(query).all()
    return [
        {
            "name": name,
            "crawls": n,
            "pages": pages,
            "last_crawl_at": last.replace(tzinfo=UTC).isoformat() if last else None,
        }
        for name, n, pages, last in rows
    ]


def project_crawls(engine: sa.Engine, name: str) -> list[storage.CrawlRow]:
    if name not in {p["name"] for p in list_projects(engine)}:
        raise InvalidArguments(f"No project '{name}' — see 'spider projects list'.")
    return [r for r in storage.list_crawls(engine) if r.project == name]


def delete_project(engine: sa.Engine, name: str) -> tuple[int, int]:
    """Delete a project with all its crawls; returns (crawls, pages) deleted."""
    rows = project_crawls(engine, name)
    pages = delete_crawls(engine, rows)
    with engine.begin() as conn:
        conn.execute(sa.delete(projects).where(projects.c.name == name))
    return len(rows), pages


@dataclass
class DbInfo:
    path: str  # the SQLite file, or the PostgreSQL URL without its password
    size_bytes: int  # the database file with its WAL (PostgreSQL: pg_database_size)
    html_path: str | None
    html_size_bytes: int
    free_bytes: int  # unused pages inside the file: what `vacuum` would give back
    sqlite_version: str
    schema_revision: str | None
    schema_head: str
    pending_migrations: list[str]
    projects: int
    crawls: int
    pages: int
    links: int
    issues: int
    engine: str = "sqlite"  # sqlite | postgresql
    server_version: str | None = None  # PostgreSQL's


def _file_size(path: Path) -> int:
    return sum(p.stat().st_size for p in (path, path.with_name(path.name + "-wal")) if p.is_file())


def _revisions(engine: sa.Engine) -> tuple[str | None, str, list[str]]:
    """(current revision, head revision, revisions still to apply, oldest first)."""
    script = ScriptDirectory.from_config(db.alembic_config())
    head = script.get_current_head() or ""
    state = db.schema_state(engine)
    if state.too_new:  # a newer release migrated it: the history here can't reach its revision
        raise DatabaseTooNew(state.current or "")
    current = state.current
    if current is None and not storage.is_sqlite(engine):  # a new PostgreSQL: the baseline of 0033, then the rest
        later = [rev.revision for rev in script.iterate_revisions(head, db.BASELINE)]
        return current, head, [db.BASELINE, *reversed(later)]
    pending = [rev.revision for rev in script.iterate_revisions(head, current)]
    return current, head, list(reversed(pending))


def db_info(engine: sa.Engine) -> DbInfo:
    path = Path(engine.url.database or "")
    current, head, pending = _revisions(engine)
    counts = dict.fromkeys(("projects", "crawls", "pages", "links", "issues"), 0)
    with engine.connect() as conn:
        tables = set(sa.inspect(conn).get_table_names())
        for name in counts:
            # a local file not migrated yet still has the names from before 0033 (and before 0014, `links`)
            candidates = {"links": ("spider_link_rows", "link_rows", "links")}.get(name, (f"spider_{name}", name))
            source = next((t for t in candidates if t in tables), None)
            if source is not None:
                counts[name] = conn.exec_driver_sql(f"SELECT count(*) FROM {source}").scalar_one()  # noqa: S608 — fixed names
        if storage.is_sqlite(conn):
            free = conn.exec_driver_sql("PRAGMA freelist_count").scalar_one()
            free *= conn.exec_driver_sql("PRAGMA page_size").scalar_one()
            size, server = _file_size(path), None
        else:  # PostgreSQL: the shared database — only spider's own tables count; VACUUM reclaims deleted crawls
            free = 0
            size = _pg_size(conn)
            server = conn.exec_driver_sql("SHOW server_version").scalar_one()
    html = storage.html_db_path()
    return DbInfo(
        path=str(path) if storage.is_sqlite(engine) else engine.url.render_as_string(hide_password=True),
        size_bytes=size,
        html_path=str(html) if html.is_file() else None,
        html_size_bytes=_file_size(html) if html.is_file() else 0,
        free_bytes=free,
        sqlite_version=sqlite3.sqlite_version,
        schema_revision=current,
        schema_head=head,
        pending_migrations=pending,
        **counts,
        engine=engine.dialect.name,
        server_version=server,
    )


def migrate(engine: sa.Engine) -> list[str]:
    """Apply pending migrations; returns the revisions applied."""
    _, _, pending = _revisions(engine)
    if pending:
        db.upgrade(engine)
    return pending


def _pg_tables(conn: sa.Connection) -> list[str]:
    """Spider's tables that exist, schema-qualified where they have a schema (the cache tables)."""
    return [
        t.fullname for t in storage.metadata.sorted_tables if sa.inspect(conn).has_table(t.name, schema=t.schema)
    ]


def _pg_size(conn: sa.Connection) -> int:
    """Bytes of spider's tables with their indexes — not the whole shared database."""
    names = _pg_tables(conn)
    if not names:
        return 0
    query = sa.text(
        "SELECT coalesce(sum(pg_total_relation_size(CAST(t AS regclass))), 0) FROM unnest(CAST(:names AS text[])) AS t"
    )
    return int(conn.execute(query, {"names": names}).scalar_one())


def vacuum(engine: sa.Engine) -> tuple[int, int]:
    """Rewrite the database (and the stored-HTML one) without free pages; returns total bytes (before, after).

    PostgreSQL: VACUUM FULL of spider's tables — it rewrites them and locks them meanwhile."""
    html = storage.html_db_path()
    if not storage.is_sqlite(engine):
        html_before = _file_size(html) if html.is_file() else 0
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
            before = _pg_size(conn) + html_before
            for name in _pg_tables(conn):  # never a bare VACUUM FULL: the database is shared
                conn.exec_driver_sql(f"VACUUM FULL {name}")
            after_db = _pg_size(conn)
        if html.is_file():
            _vacuum_file(html)
        return before, after_db + (_file_size(html) if html.is_file() else 0)
    main = Path(engine.url.database or "")
    files = [main, *([html] if html.is_file() else [])]
    before = sum(_file_size(f) for f in files)
    for path in files:
        _vacuum_file(path)
    return before, sum(_file_size(f) for f in files)


def _vacuum_file(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except sqlite3.OperationalError as exc:  # "database is locked": a crawl is writing
        raise InvalidArguments(
            f"Cannot vacuum {path.name} while it is in use ({exc}) — wait for crawls to end."
        ) from exc
    finally:
        conn.close()
