"""Getting data out: one URL in full, whole tables as CSV / JSON, and read-only SQL.

Exports stream: rows go from the SQLite cursor straight to the file, so a 100k-URL crawl's
3 million links never sit in memory at once (the same rule as the crawl itself). `query` opens
the database read-only and lets SQLite itself refuse anything but reading (an authorizer), so an
agent can ask arbitrary questions without being able to change or attach anything.
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

import sqlalchemy as sa
from pydantic import ValidationError

from . import enrich, issues, storage
from .errors import InvalidArguments
from .overview import CONTENT_KIND_SQL, CONTENT_KINDS
from .settings import Settings

DATASETS = ("pages", "links", "issues")
RESOURCE_KINDS = ("image", "css", "js", "media", "iframe")
_STATUS_CLASS = re.compile(r"^([1-5])xx$", re.IGNORECASE)


@dataclass
class Table:
    columns: list[str]
    rows: Iterable[tuple]


def _status_filter(value: str, column: str = "t.status_code") -> tuple[str, dict]:
    """ "404" -> exact code; "4xx" -> the class."""
    if value.isdigit():
        return f"{column} = :status", {"status": int(value)}
    match = _STATUS_CLASS.match(value)
    if not match:
        raise InvalidArguments(f"Status must be a code like 404 or a class like 4xx, got '{value}'.")
    low = int(match.group(1)) * 100
    return f"{column} BETWEEN :low AND :high", {"low": low, "high": low + 99}


def _rows(conn: sa.Connection, sql: str, params: dict) -> Iterator[tuple]:
    result = conn.execution_options(yield_per=1000).execute(sa.text(sql), params)
    for row in result:
        yield tuple(row)


def dataset(
    conn: sa.Connection,
    crawl_id: int,
    what: str,
    *,
    issue: str | None = None,
    target_status: str | None = None,
    external: bool = False,
    kind: str | None = None,
) -> Table:
    """A crawl's `pages`, `links` (with the target's status code) or `issues` (with rule names), filtered."""
    params: dict[str, Any] = {"crawl_id": crawl_id}
    if kind is not None and what != "pages":
        raise InvalidArguments("--type filters pages, not links or issues.")
    if what == "pages":
        columns = [c.name for c in storage.pages.columns if c.name != "crawl_id"] + ["content_kind"]
        where = "p.crawl_id = :crawl_id"
        if kind is not None:
            if kind not in CONTENT_KINDS:
                raise InvalidArguments(f"Unknown --type {kind}: one of {', '.join(CONTENT_KINDS)}.")
            where += f" AND ({CONTENT_KIND_SQL}) = :kind"
            params["kind"] = kind
        if issue is not None:
            issues.rule(issue)
            where += " AND p.url IN (SELECT url FROM issues WHERE crawl_id = :crawl_id AND code = :code)"
            params["code"] = issue
        if external:
            where += " AND coalesce(p.external, 0)"
        if target_status is not None:
            clause, extra = _status_filter(target_status, "p.status_code")
            where, params = f"{where} AND {clause}", params | extra
        select = ", ".join(f"p.{c}" for c in columns[:-1])
        sql = f"SELECT {select}, {CONTENT_KIND_SQL} FROM pages p WHERE {where} ORDER BY p.url"  # noqa: S608 — fixed names, bound values
    elif what == "links":
        columns = [c.name for c in storage.links.columns if c.name != "crawl_id"] + ["target_status"]
        where = "l.crawl_id = :crawl_id"
        if external:
            where += " AND NOT l.internal"
        if target_status is not None:
            clause, extra = _status_filter(target_status)
            where, params = f"{where} AND {clause}", params | extra
        if issue is not None:
            raise InvalidArguments("--issue filters pages or issues, not links.")
        select = ", ".join(f"l.{c}" for c in columns[:-1])
        sql = (
            f"SELECT {select}, t.status_code FROM links l"  # noqa: S608 — fixed names, bound values
            " LEFT JOIN pages t ON t.crawl_id = l.crawl_id AND t.url = l.target"
            f" WHERE {where} ORDER BY l.source, l.target"
        )
    elif what == "issues":
        return _issues_table(conn, crawl_id, issue)
    else:
        raise InvalidArguments(f"Unknown dataset '{what}': one of {', '.join(DATASETS)}.")
    return Table(columns, _rows(conn, sql, params))


def _issues_table(conn: sa.Connection, crawl_id: int, issue: str | None) -> Table:
    columns = ["code", "group", "name", "type", "priority", "url", "status_code", "detail"]
    params: dict[str, Any] = {"crawl_id": crawl_id}
    where = "i.crawl_id = :crawl_id"
    if issue is not None:
        issues.rule(issue)
        where += " AND i.code = :code"
        params["code"] = issue
    sql = (
        "SELECT i.code, i.url, p.status_code, i.detail FROM issues i"  # noqa: S608 — fixed text
        " LEFT JOIN pages p ON p.crawl_id = i.crawl_id AND p.url = i.url"
        f" WHERE {where} ORDER BY i.code, i.url"
    )

    def rows() -> Iterator[tuple]:
        for code, url, status, detail in _rows(conn, sql, params):
            rule = issues.BY_CODE.get(code)
            meta = (rule.group, rule.name, rule.type, rule.priority) if rule else (None, None, None, None)
            yield (code, *meta, url, status, detail)

    return Table(columns, rows())


def write(table: Table, fmt: str, out: IO[str]) -> int:
    """Stream a table as CSV (header row) or a JSON array of objects; returns the number of rows."""
    count = 0
    if fmt == "csv":
        writer = csv.writer(out)
        writer.writerow(table.columns)
        for row in table.rows:
            writer.writerow(row)
            count += 1
        return count
    if fmt == "json":
        out.write("[")
        for row in table.rows:
            out.write(",\n" if count else "\n")
            out.write(json.dumps(dict(zip(table.columns, row, strict=True)), ensure_ascii=False, default=str))
            count += 1
        out.write("\n]\n" if count else "]\n")
        return count
    raise InvalidArguments(f"Unknown format '{fmt}': csv or json.")


# --- read-only SQL -------------------------------------------------------------------

_ALLOWED = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}


def _authorize(action: int, *_args) -> int:
    return sqlite3.SQLITE_OK if action in _ALLOWED else sqlite3.SQLITE_DENY


@contextmanager
def read_only(path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """A connection that can only read: opened read-only, and SQLite refuses anything but SELECT."""
    path = path or storage.db_path()
    if not path.is_file():
        raise InvalidArguments("No crawl database yet — run 'spider crawl <url>' first.")
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
    conn.create_function("casefold", 1, lambda s: s.casefold() if s else s, deterministic=True)
    conn.set_authorizer(_authorize)
    try:
        yield conn
    finally:
        conn.close()


def query(conn: sqlite3.Connection, sql: str) -> Table:
    try:
        cursor = conn.execute(sql)
    except sqlite3.DatabaseError as exc:  # syntax error, unknown table, or a write the authorizer refused
        raise InvalidArguments(f"Query failed: {exc}. Only SELECT is allowed; tables: `spider db info`.") from exc
    if cursor.description is None:
        raise InvalidArguments("Not a query: only SELECT (and WITH … SELECT) is allowed.")
    return Table([d[0] for d in cursor.description], cursor)


# --- one URL ------------------------------------------------------------------------


def url_details(engine: sa.Engine, crawl_id: int, url: str) -> dict:
    """Everything about one URL of a crawl: its row, its issues, link counts and the resources it loads."""
    pages, links = storage.pages, storage.links
    with engine.connect() as conn:
        row = conn.execute(sa.select(pages).where(pages.c.crawl_id == crawl_id, pages.c.url == url)).mappings().first()
        if row is None:
            raise InvalidArguments(f"No {url} in crawl #{crawl_id} — see 'spider urls' or 'spider query'.")
        page = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in row.items() if k != "crawl_id"}
        page["headers"] = json.loads(page["headers"]) if page.get("headers") else None
        found = conn.execute(
            sa.select(storage.issues.c.code, storage.issues.c.detail)
            .where(storage.issues.c.crawl_id == crawl_id, storage.issues.c.url == url)
            .order_by(storage.issues.c.code)
        ).all()

        def count(column: sa.Column, kinds: tuple[str, ...]) -> int:
            where = sa.and_(links.c.crawl_id == crawl_id, column == url, links.c.kind.in_(kinds))
            return conn.execute(sa.select(sa.func.count()).select_from(links).where(where)).scalar_one()

        target = sa.alias(pages, "t")
        resources = conn.execute(
            sa.select(
                links.c.target,
                links.c.kind,
                links.c.alt,
                links.c.alt_attr,
                links.c.sized,
                target.c.status_code,
                target.c.bytes,
            )
            .select_from(
                links.outerjoin(target, sa.and_(target.c.crawl_id == links.c.crawl_id, target.c.url == links.c.target))
            )
            .where(links.c.crawl_id == crawl_id, links.c.source == url, links.c.kind.in_(RESOURCE_KINDS))
            .order_by(links.c.kind, links.c.target)
        ).mappings()
        resource_rows = [dict(r) for r in resources]
        hyperlinks = ("hyperlink",)
        counts = {"inlinks": count(links.c.target, hyperlinks), "outlinks": count(links.c.source, hyperlinks)}
    issue_rows = []
    for code, detail in found:
        rule = issues.BY_CODE.get(code)
        issue_rows.append(
            {
                "code": code,
                "name": rule.name if rule else code,
                "type": rule.type if rule else None,
                "priority": rule.priority if rule else None,
                "detail": detail,
            }
        )
    return {"crawl_id": crawl_id, "page": page, "request_headers": _request_headers(engine, crawl_id),
            "issues": issue_rows, **counts, "resources": resource_rows,
            "metrics": enrich.metrics_of(engine, crawl_id, url)}  # fmt: skip


def _request_headers(engine: sa.Engine, crawl_id: int) -> dict[str, str]:
    """What the crawl sent with every request: its settings' headers and User-Agent (the client adds the rest)."""
    _, snapshot = storage.get_crawl(engine, crawl_id)
    try:
        crawl = Settings.model_validate(snapshot or {}).crawl
    except ValidationError:  # a snapshot from an older spider
        return {}
    agent = crawl.resolved_user_agent
    return {**crawl.headers, "User-Agent": agent or "(браузерный по умолчанию — Firefox)"}
