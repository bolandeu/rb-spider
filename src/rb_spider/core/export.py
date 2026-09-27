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
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

import sqlalchemy as sa
from pydantic import ValidationError

from . import enrich, issues, serp, storage, structured
from .errors import InvalidArguments
from .overview import CONTENT_KIND_SQL, CONTENT_KINDS
from .settings import Settings, ThresholdSettings

DATASETS = ("pages", "links", "issues", "queued", "headers", "cookies", "source", "text", "duplicates", "custom",
            "sitemap-urls", "javascript", "rendered-source", "screenshots")  # fmt: skip
# Bulk Export «Links» by issue: the link rows behind a link rule (Screaming Frog exports the links, not the pages)
LINK_ISSUES = {
    "links_internal_nofollow_outlinks": "l.kind = 'hyperlink' AND l.internal AND l.nofollow",
    "links_nofollow_inlinks_only": "l.kind = 'hyperlink' AND l.internal AND l.nofollow",
    "links_follow_and_nofollow_inlinks": "l.kind = 'hyperlink' AND l.internal AND l.nofollow",
    "links_no_anchor_text": "l.kind = 'hyperlink' AND l.internal AND trim(coalesce(l.anchor, '')) = ''"
    " AND trim(coalesce(l.alt, '')) = ''",
    "links_outlinks_to_localhost": "l.kind = 'hyperlink' AND NOT l.internal AND (l.target LIKE 'http://localhost%'"
    " OR l.target LIKE 'https://localhost%' OR l.target LIKE 'http://127.%' OR l.target LIKE 'https://127.%')",
    "images_missing_alt_text": "l.kind = 'image' AND l.alt_attr AND trim(coalesce(l.alt, '')) = ''",
    "images_missing_alt_attribute": "l.kind = 'image' AND NOT l.alt_attr",
    "images_missing_size": "l.kind = 'image' AND NOT l.sized",
    "internal_client_error": "t.status_code BETWEEN 400 AND 499 AND NOT coalesce(t.external, FALSE)",
    "internal_server_error": "t.status_code >= 500 AND NOT coalesce(t.external, FALSE)",
    "external_client_error": "t.status_code BETWEEN 400 AND 499 AND coalesce(t.external, FALSE)",
    "external_server_error": "t.status_code >= 500 AND coalesce(t.external, FALSE)",
    "security_mixed_content": "l.source LIKE 'https://%' AND l.target LIKE 'http://%'"
    " AND l.kind IN ('image', 'css', 'js', 'media', 'iframe')",
    "security_form_url_insecure": "l.source LIKE 'https://%' AND l.target LIKE 'http://%' AND l.kind = 'form'",
}
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
    result = storage.streamed(conn, 1000).execute(sa.text(sql), params)
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
    scheme: str | None = None,
) -> Table:
    """A crawl's `pages`, `links` (with the target's status code) or `issues` (with rule names), filtered."""
    params: dict[str, Any] = {"crawl_id": crawl_id}
    if kind is not None and what != "pages":
        raise InvalidArguments("--type filters pages, not links or issues.")
    if scheme is not None and (what != "pages" or scheme not in ("http", "https")):
        raise InvalidArguments("--scheme is http or https, and filters pages only.")
    if what == "pages":
        columns = [c.name for c in storage.pages.columns if c.name != "crawl_id"] + ["content_kind"]
        where = "p.crawl_id = :crawl_id"
        if kind is not None:
            if kind not in CONTENT_KINDS:
                raise InvalidArguments(f"Unknown --type {kind}: one of {', '.join(CONTENT_KINDS)}.")
            where += f" AND ({CONTENT_KIND_SQL}) = :kind"
            params["kind"] = kind
        if scheme is not None:
            if scheme not in ("http", "https"):
                raise InvalidArguments("--scheme: http or https.")
            where += f" AND p.url GLOB '{scheme}://*'"  # a literal: GLOB uses the index
        if issue is not None:
            issues.rule(issue)
            where += " AND p.url IN (SELECT url FROM issues WHERE crawl_id = :crawl_id AND code = :code)"
            params["code"] = issue
        if external:
            where += " AND coalesce(p.external, FALSE)"
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
            issues.rule(issue)
            if issue not in LINK_ISSUES:
                raise InvalidArguments(
                    f"--issue for links: one of {', '.join(LINK_ISSUES)} (other rules: pages or issues)."
                )
            where += f" AND ({LINK_ISSUES[issue]})"
        select = ", ".join(f"l.{c}" for c in columns[:-1])
        sql = (
            f"SELECT {select}, t.status_code FROM links l"  # noqa: S608 — fixed names, bound values
            " LEFT JOIN pages t ON t.crawl_id = l.crawl_id AND t.url = l.target"
            f" WHERE {where} ORDER BY l.source, l.target"
        )
    elif what == "issues":
        return _issues_table(conn, crawl_id, issue)
    elif what in _EXTRA:
        if issue is not None or target_status is not None or external:
            raise InvalidArguments(f"--issue / --status / --external filter pages, links or issues, not {what}.")
        return _EXTRA[what](conn, crawl_id)
    else:
        raise InvalidArguments(f"Unknown dataset '{what}': one of {', '.join(DATASETS)}.")
    return Table(columns, _rows(conn, sql, params))


def _sql_table(conn: sa.Connection, crawl_id: int, sql: str) -> Table:
    result = storage.streamed(conn, 1000).execute(sa.text(sql), {"crawl_id": crawl_id})
    return Table(list(result.keys()), (tuple(row) for row in result))


def _pages_json(conn: sa.Connection, crawl_id: int, columns: list[str], rows_of) -> Table:
    """A table whose rows come from each page's headers JSON — parsed a page at a time."""
    sql = sa.text("SELECT url, headers FROM pages WHERE crawl_id = :crawl_id AND headers IS NOT NULL ORDER BY url")

    def rows() -> Iterator[tuple]:
        for url, raw in storage.streamed(conn, 500).execute(sql, {"crawl_id": crawl_id}):
            yield from rows_of(url, json.loads(raw))

    return Table(columns, rows())


def _headers(url: str, headers: dict) -> Iterator[tuple]:
    for name, value in headers.items():
        yield url, name, value


_COOKIE_SPLIT = re.compile(r",\s*(?=[^;,=\s]+=)")  # a folded Set-Cookie list: split before the next name=


def cookies_of(headers: dict) -> list[dict]:
    """The cookies a response sets: name, value and attributes (Path, Domain, Secure, HttpOnly, SameSite…)."""
    found = []
    for item in _COOKIE_SPLIT.split(headers.get("set-cookie", "")):
        name, sep, rest = item.strip().partition("=")
        if not sep or not name:
            continue
        value, *attributes = rest.split(";")
        attrs = {}
        for attribute in attributes:
            key, _, val = attribute.strip().partition("=")
            if key:
                attrs[key.strip().lower()] = val.strip() or True
        found.append({"name": name.strip(), "value": value.strip(), **attrs})
    return found


def _cookies(url: str, headers: dict) -> Iterator[tuple]:
    for cookie in cookies_of(headers):
        yield (url, cookie["name"], cookie["value"], cookie.get("domain"), cookie.get("path"), cookie.get("expires"),
               "secure" in cookie, "httponly" in cookie, cookie.get("samesite"))  # fmt: skip


def _stored_html(conn: sa.Connection, crawl_id: int, as_text: bool, rendered: bool = False) -> Table:
    """Page source (or the DOM after JavaScript) or visible text of every stored page (`--store-html`), one page at a
    time."""
    from .extract import visible_text

    sql = sa.text(
        "SELECT url FROM pages WHERE crawl_id = :crawl_id AND parsed AND content_type LIKE '%html%' ORDER BY url"
    )

    def rows() -> Iterator[tuple]:
        for (url,) in storage.streamed(conn, 500).execute(sql, {"crawl_id": crawl_id}):
            body = storage.get_html(crawl_id, url, rendered=rendered)
            if body is not None:
                yield url, visible_text(body) if as_text else body.decode("utf-8", "replace")

    return Table(["url", "text" if as_text else "html"], rows())


_EXTRA = {
    "queued": lambda conn, crawl_id: _sql_table(conn, crawl_id,
        "SELECT url, depth, check_only FROM frontier WHERE crawl_id = :crawl_id AND NOT done ORDER BY depth, url"),
    "headers": lambda conn, crawl_id: _pages_json(conn, crawl_id, ["url", "name", "value"], _headers),
    "cookies": lambda conn, crawl_id: _pages_json(conn, crawl_id, ["url", "name", "value", "domain", "path", "expires",
                                                                  "secure", "httponly", "samesite"], _cookies),
    "source": lambda conn, crawl_id: _stored_html(conn, crawl_id, as_text=False),
    "text": lambda conn, crawl_id: _stored_html(conn, crawl_id, as_text=True),
    "rendered-source": lambda conn, crawl_id: _stored_html(conn, crawl_id, as_text=False, rendered=True),
    "screenshots": lambda conn, crawl_id: _sql_table(conn, crawl_id,
        "SELECT url, screenshot FROM pages WHERE crawl_id = :crawl_id AND screenshot IS NOT NULL ORDER BY url"),
    "duplicates": lambda conn, crawl_id: _sql_table(conn, crawl_id,
        "SELECT url_a, url_b, similarity FROM near_duplicates WHERE crawl_id = :crawl_id ORDER BY similarity DESC, url_a"),
    "custom": lambda conn, crawl_id: _sql_table(conn, crawl_id,
        "SELECT kind, name, url, value, n FROM custom_values WHERE crawl_id = :crawl_id ORDER BY kind, name, url, n"),
    "sitemap-urls": lambda conn, crawl_id: _sql_table(conn, crawl_id,
        "SELECT url, source, lastmod FROM sitemap_urls WHERE crawl_id = :crawl_id ORDER BY url, source"),
    "javascript": lambda conn, crawl_id: _sql_table(conn, crawl_id,
        "SELECT url, kind, message, resource FROM render_events WHERE crawl_id = :crawl_id ORDER BY url, kind"),
}  # fmt: skip


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
    raise InvalidArguments(f"Unknown format '{fmt}': csv, json or xlsx.")


def preset_tables(conn: sa.Connection, crawl_id: int, specs: list[str]) -> Iterator[tuple[str, Table]]:
    """The tables of a preset: `dataset` or `dataset:issue code` (pages / links / issues of one rule)."""
    for spec in specs:
        what, _, code = spec.partition(":")
        if what not in DATASETS:
            raise InvalidArguments(f"Preset entry '{spec}': unknown dataset — one of {', '.join(DATASETS)}.")
        yield spec.replace(":", "-"), dataset(conn, crawl_id, what, issue=code or None)


XLSX_CELL = 32_767  # Excel's limit on one cell's text


def _cell(value):
    """An Excel cell: text cut to Excel's limit; a time without its zone (Excel has none — PostgreSQL gives UTC)."""
    if isinstance(value, str):
        return value[:XLSX_CELL]
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def write_xlsx(sheets: Iterable[tuple[str, Table]], path: Path) -> dict[str, int]:
    """Tables as sheets of one .xlsx, streamed (openpyxl write-only: rows go to disk as they come).
    Returns rows per sheet; text over Excel's cell limit is cut."""
    from openpyxl import Workbook

    book = Workbook(write_only=True)
    counts: dict[str, int] = {}
    for title, table in sheets:
        name = re.sub(r"[\[\]:*?/\\]", "-", title)[:31] or "sheet"
        sheet = book.create_sheet(name)
        sheet.append(table.columns)
        n = 0
        for row in table.rows:
            sheet.append([_cell(v) for v in row])
            n += 1
        counts[name] = n
    book.save(path)
    return counts


# --- read-only SQL -------------------------------------------------------------------

_ALLOWED = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}


def _authorize(action: int, *_args) -> int:
    return sqlite3.SQLITE_OK if action in _ALLOWED else sqlite3.SQLITE_DENY


_QUERY_FAILED = "Query failed: {}. Only SELECT is allowed; tables: `spider db info`."


class _PgReadOnly:
    """PostgreSQL for `spider query`: a read-only transaction, one statement per call (a prepared statement can't
    hold several — `COMMIT; DELETE …` never gets past the parser). For a hard guarantee, give SPIDER_DB_URL a user
    with SELECT rights only."""

    def __init__(self, url: str) -> None:
        import psycopg
        from psycopg import sql as pg_sql

        self.error, self.sql = psycopg.Error, pg_sql.SQL
        target = storage.remote_url(url).set(drivername="postgresql")
        self.conn = psycopg.connect(target.render_as_string(hide_password=False))
        self.conn.read_only = True

    def execute(self, sql: str):
        cursor = self.conn.cursor()
        try:
            cursor.execute(self.sql(sql), prepare=True)  # ty: ignore[invalid-argument-type] — the user's text, not a literal
        except self.error as exc:
            raise InvalidArguments(_QUERY_FAILED.format(str(exc).strip())) from exc
        return cursor

    def close(self) -> None:
        self.conn.rollback()
        self.conn.close()


@contextmanager
def read_only(path: Path | None = None) -> Iterator:
    """A connection that can only read: SQLite opened read-only with an authorizer that refuses anything but SELECT,
    or (SPIDER_DB_URL) a read-only PostgreSQL transaction."""
    if path is None and (url := storage.db_url()):
        pg = _PgReadOnly(url)
        try:
            yield pg
        finally:
            pg.close()
        return
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


def query(conn, sql: str) -> Table:
    try:
        cursor = conn.execute(sql)
    except sqlite3.DatabaseError as exc:  # syntax error, unknown table, or a write the authorizer refused
        raise InvalidArguments(_QUERY_FAILED.format(exc)) from exc
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
        for column in ("sd_messages", "sd_features"):
            page[column] = json.loads(page[column]) if page.get(column) else None
        found = conn.execute(
            sa.select(storage.issues.c.code, storage.issues.c.detail)
            .where(storage.issues.c.crawl_id == crawl_id, storage.issues.c.url == url)
            .order_by(storage.issues.c.code)
        ).all()

        def count(column: sa.Column, kinds: tuple[str, ...]) -> int:
            where = sa.and_(links.c.crawl_id == crawl_id, column == url, links.c.kind.in_(kinds))
            return conn.execute(sa.select(sa.func.count()).select_from(links).where(where)).scalar_one()

        target = sa.alias(pages, "t")
        shown = (  # as the rendered page laid the image out (crawl.render_images): one row per image
            sa.select(storage.rendered_images.c.crawl_id, storage.rendered_images.c.url, storage.rendered_images.c.image,
                      sa.func.max(storage.rendered_images.c.display_width).label("display_width"),
                      sa.func.max(storage.rendered_images.c.display_height).label("display_height"))
            .where(storage.rendered_images.c.crawl_id == crawl_id, storage.rendered_images.c.url == url)
            .group_by(storage.rendered_images.c.crawl_id, storage.rendered_images.c.url, storage.rendered_images.c.image)
            .subquery("shown")
        )  # fmt: skip
        resources = conn.execute(
            sa.select(
                links.c.target,
                links.c.kind,
                links.c.alt,
                links.c.alt_attr,
                links.c.sized,
                links.c.origin,
                target.c.status_code,
                target.c.bytes,
                target.c.image_width.label("real_width"),
                target.c.image_height.label("real_height"),
                shown.c.display_width,
                shown.c.display_height,
            )
            .select_from(
                links.outerjoin(
                    target, sa.and_(target.c.crawl_id == links.c.crawl_id, target.c.url == links.c.target)
                ).outerjoin(
                    shown,
                    sa.and_(
                        shown.c.crawl_id == links.c.crawl_id,
                        shown.c.url == links.c.source,
                        shown.c.image == links.c.target,
                    ),
                )
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
            "metrics": enrich.metrics_of(engine, crawl_id, url),
            "serp": serp.snippet(url, page.get("title"), page.get("meta_description"), _thresholds(engine, crawl_id))
            if page.get("parsed") and (page.get("title") or page.get("meta_description")) else None,
            "structured_data": _structured_items(engine, crawl_id, url)}  # fmt: skip


def _thresholds(engine: sa.Engine, crawl_id: int) -> ThresholdSettings:
    """The thresholds the crawl ran with (its settings snapshot), the defaults for older crawls."""
    _, snapshot = storage.get_crawl(engine, crawl_id)
    try:
        return Settings.model_validate(snapshot or {}).thresholds
    except ValidationError:
        return ThresholdSettings()


def _structured_items(engine: sa.Engine, crawl_id: int, url: str) -> list[dict] | None:
    """Structured Data Details: the page's items, re-read from its stored HTML (`--store-html`), None without it."""
    body = storage.get_html(crawl_id, url)
    _, snapshot = storage.get_crawl(engine, crawl_id)
    try:
        formats = tuple(Settings.model_validate(snapshot or {}).collect.structured_data)
    except ValidationError:
        formats = ()
    if body is None or not formats:
        return None
    from selectolax.lexbor import LexborHTMLParser

    return structured.extract(LexborHTMLParser(body), body, url, formats, keep_items=True).items


def _request_headers(engine: sa.Engine, crawl_id: int) -> dict[str, str]:
    """What the crawl sent with every request: its settings' headers and User-Agent (the client adds the rest)."""
    _, snapshot = storage.get_crawl(engine, crawl_id)
    try:
        crawl = Settings.model_validate(snapshot or {}).crawl
    except ValidationError:  # a snapshot from an older spider
        return {}
    agent = crawl.resolved_user_agent
    return {**crawl.headers, "User-Agent": agent or "(браузерный по умолчанию — Firefox)"}


def copy_screenshots(conn: sa.Connection, crawl_id: int, folder: Path) -> int:
    """Bulk Export > Screenshots: the crawl's screenshots copied into `folder`, named after their pages, with an
    index.csv (url, file). Returns how many were copied."""
    import csv
    import shutil

    folder.mkdir(parents=True, exist_ok=True)
    sql = sa.text(
        "SELECT url, screenshot FROM pages WHERE crawl_id = :crawl_id AND screenshot IS NOT NULL ORDER BY url"
    )
    count = 0
    with (folder / "index.csv").open("w", encoding="utf-8", newline="") as index:
        writer = csv.writer(index)
        writer.writerow(["url", "file"])
        for url, shot in storage.streamed(conn, 1000).execute(sql, {"crawl_id": crawl_id}):
            if not Path(shot).is_file():  # the file was removed by hand: the row stays out of the index
                continue
            name = f"{count + 1:05d}-{_slug(url)}.jpg"
            shutil.copyfile(shot, folder / name)
            writer.writerow([url, name])
            count += 1
    return count


def _slug(url: str) -> str:
    """A short, file-name-safe version of a URL."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", url.split("://", 1)[-1]).strip("-")[:80] or "page"
