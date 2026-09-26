"""SEO checks over a stored crawl: each rule turns crawl tables into (url, detail) findings.

Rules run after the crawl, never during it — memory stays flat, and `spider analyze` can
re-run them on an old crawl (new rules, changed thresholds) without fetching anything.
Most rules are one SQL query; the ones that need graph walking are Python. Codes, types and
priorities follow Screaming Frog's issue library (docs/features.md, docs/reference/).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import sqlalchemy as sa

from . import storage
from .errors import InvalidArguments

Finding = tuple[str, str | None]  # (url, detail)


@dataclass(frozen=True)
class Rule:
    code: str
    group: str
    name: str
    type: Literal["issue", "warning", "opportunity"]
    priority: Literal["high", "medium", "low"]
    description: str
    find: Callable[[sa.Connection, int], list[Finding]]


def _sql(where: str, detail: str = "NULL") -> Callable[[sa.Connection, int], list[Finding]]:
    """A rule that is a filter over the crawl's pages."""
    query = sa.text(f"SELECT url, {detail} FROM pages WHERE crawl_id = :crawl_id AND ({where}) ORDER BY url")  # noqa: S608 — fixed rule text, crawl_id is bound

    def find(conn: sa.Connection, crawl_id: int) -> list[Finding]:
        return [(url, detail) for url, detail in conn.execute(query, {"crawl_id": crawl_id})]

    return find


def _redirect_graph(conn: sa.Connection, crawl_id: int) -> dict[str, str]:
    """url -> where it sends the client (server 3xx or meta/HTTP refresh). Only redirecting URLs: small."""
    rows = conn.execute(
        sa.select(storage.pages.c.url, sa.func.coalesce(storage.pages.c.redirect_url, storage.pages.c.refresh_url))
        .where(storage.pages.c.crawl_id == crawl_id)
        .where(sa.or_(storage.pages.c.redirect_url.is_not(None), storage.pages.c.refresh_url.is_not(None)))
    )
    return {url: target for url, target in rows}


def _follow(graph: dict[str, str], start: str) -> tuple[list[str], bool]:
    """Hops from `start` until a non-redirecting URL; the flag says the path came back on itself."""
    path, seen = [start], {start}
    while (nxt := graph.get(path[-1])) is not None:
        if nxt in seen:
            return [*path, nxt], True
        path.append(nxt)
        seen.add(nxt)
    return path, False


def _redirect_loops(conn: sa.Connection, crawl_id: int) -> list[Finding]:
    graph = _redirect_graph(conn, crawl_id)
    found = []
    for url in sorted(graph):
        path, loops = _follow(graph, url)
        if loops:
            found.append((url, " → ".join(path)))
    return found


def _redirect_chains(conn: sa.Connection, crawl_id: int) -> list[Finding]:
    """Redirects that land on another redirect: 2+ hops before the final URL (loops are their own rule)."""
    graph = _redirect_graph(conn, crawl_id)
    found = []
    for url in sorted(graph):
        path, loops = _follow(graph, url)
        if not loops and len(path) > 2:
            found.append((url, f"{len(path) - 1} hops: " + " → ".join(path)))
    return found


RULES: list[Rule] = [
    Rule(
        "internal_no_response",
        "Response Codes",
        "Internal No Response",
        "issue",
        "high",
        "Внутренний URL не ответил вовсе: таймаут, отказ соединения, ошибка TLS.",
        _sql("status_code = 0 AND error IS NOT NULL", "error"),
    ),
    Rule(
        "internal_client_error",
        "Response Codes",
        "Internal Client Error (4XX)",
        "issue",
        "high",
        "Внутренний URL отдаёт 4xx (например, 404): ссылки на него битые.",
        _sql("status_code BETWEEN 400 AND 499", "CAST(status_code AS TEXT)"),
    ),
    Rule(
        "internal_server_error",
        "Response Codes",
        "Internal Server Error (5XX)",
        "issue",
        "high",
        "Внутренний URL отдаёт 5xx: сервер не смог ответить.",
        _sql("status_code BETWEEN 500 AND 599", "CAST(status_code AS TEXT)"),
    ),
    Rule(
        "internal_redirect_loop",
        "Response Codes",
        "Internal Redirect Loop",
        "issue",
        "high",
        "Цепочка редиректов возвращается на уже пройденный URL: страница не открывается никогда.",
        _redirect_loops,
    ),
    Rule(
        "internal_blocked_by_robots",
        "Response Codes",
        "Internal Blocked by Robots.txt",
        "warning",
        "high",
        "URL запрещён в robots.txt: поисковик не сможет его обойти (краулер тоже не скачивал).",
        _sql("blocked = 'robots_txt'"),
    ),
    Rule(
        "internal_redirect_chain",
        "Response Codes",
        "Internal Redirect Chain",
        "warning",
        "medium",
        "Редирект ведёт на URL, который снова редиректит: лишние прыжки теряют время и вес ссылок.",
        _redirect_chains,
    ),
    Rule(
        "internal_redirection_3xx",
        "Response Codes",
        "Internal Redirection (3XX)",
        "warning",
        "low",
        "Внутренний URL отдаёт серверный редирект (301, 302…): ссылки лучше вести сразу на цель.",
        _sql("status_code BETWEEN 300 AND 399", "CAST(status_code AS TEXT) || ' → ' || coalesce(redirect_url, '?')"),
    ),
    Rule(
        "internal_redirection_meta_refresh",
        "Response Codes",
        "Internal Redirection (Meta Refresh)",
        "warning",
        "low",
        'Редирект через <meta http-equiv="refresh"> в браузере — хуже серверного 301.',
        _sql("refresh_kind = 'meta'", "refresh_url"),
    ),
    Rule(
        "internal_redirection_http_refresh",
        "Response Codes",
        "Internal Redirection (HTTP Refresh)",
        "warning",
        "low",
        "Редирект через HTTP-заголовок Refresh — хуже серверного 301.",
        _sql("refresh_kind = 'http'", "refresh_url"),
    ),
]
BY_CODE = {rule.code: rule for rule in RULES}
_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def rule(code: str) -> Rule:
    if code not in BY_CODE:
        raise InvalidArguments(f"Unknown issue code '{code}'. Known codes: {', '.join(BY_CODE)}.")
    return BY_CODE[code]


def analyze(engine: sa.Engine, crawl_id: int) -> int:
    """(Re)compute every rule for a crawl, replacing earlier findings. Returns the number of findings."""
    with engine.begin() as conn:
        conn.execute(sa.delete(storage.issues).where(storage.issues.c.crawl_id == crawl_id))
        rows = [
            {"crawl_id": crawl_id, "code": r.code, "url": url, "detail": detail}
            for r in RULES
            for url, detail in r.find(conn, crawl_id)
        ]
        if rows:
            conn.execute(sa.insert(storage.issues), rows)
    return len(rows)


@dataclass
class IssueSummary:
    code: str
    group: str
    name: str
    type: str
    priority: str
    description: str
    urls: int


def summary(engine: sa.Engine, crawl_id: int) -> list[IssueSummary]:
    """Rules that found something, most urgent first (priority, then number of URLs)."""
    query = (
        sa.select(storage.issues.c.code, sa.func.count())
        .where(storage.issues.c.crawl_id == crawl_id)
        .group_by(storage.issues.c.code)
    )
    with engine.connect() as conn:
        counts = {code: n for code, n in conn.execute(query)}
    found = [
        IssueSummary(r.code, r.group, r.name, r.type, r.priority, r.description, counts[r.code])
        for r in RULES
        if r.code in counts
    ]
    return sorted(found, key=lambda s: (_PRIORITY_ORDER[s.priority], -s.urls))


def urls_with(engine: sa.Engine, crawl_id: int, code: str, limit: int | None = None) -> tuple[int, list[dict]]:
    """Total findings for one rule and the first `limit` of them, with each URL's status code."""
    rule(code)  # unknown code -> InvalidArguments
    issues, pages = storage.issues, storage.pages
    where = sa.and_(issues.c.crawl_id == crawl_id, issues.c.code == code)
    query = (
        sa.select(issues.c.url, pages.c.status_code, issues.c.detail)
        .select_from(
            issues.outerjoin(pages, sa.and_(pages.c.crawl_id == issues.c.crawl_id, pages.c.url == issues.c.url))
        )
        .where(where)
        .order_by(issues.c.url)
        .limit(limit)
    )
    with engine.connect() as conn:
        total = conn.execute(sa.select(sa.func.count()).select_from(issues).where(where)).scalar_one()
        rows = [dict(row) for row in conn.execute(query).mappings()]
    return total, rows
