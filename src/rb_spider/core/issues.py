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
from .settings import ThresholdSettings

Finding = tuple[str, str | None]  # (url, detail)


@dataclass(frozen=True)
class Rule:
    code: str
    group: str
    name: str
    type: Literal["issue", "warning", "opportunity"]
    priority: Literal["high", "medium", "low"]
    description: str
    find: Callable[[sa.Connection, int, ThresholdSettings], list[Finding]]


RuleFinder = Callable[[sa.Connection, int, ThresholdSettings], list[Finding]]

# On-page checks look at pages that are HTML and answered 200; duplicates only among indexable ones.
HTML_OK = "status_code = 200 AND content_type LIKE '%html%'"
INDEXABLE_HTML = f"{HTML_OK} AND indexable"

# Why a URL can't be indexed — Screaming Frog's Indexability Status, first matching reason wins.
_INDEXABILITY = sa.text(
    """
    UPDATE pages SET indexability_status = CASE
        WHEN blocked = 'robots_txt' THEN 'Blocked by Robots.txt'
        WHEN status_code = 0 THEN 'No Response'
        WHEN status_code BETWEEN 300 AND 399 OR refresh_url IS NOT NULL THEN 'Redirected'
        WHEN status_code BETWEEN 400 AND 499 THEN 'Client Error'
        WHEN status_code >= 500 THEN 'Server Error'
        WHEN robots_directives LIKE '%,noindex,%' OR robots_directives LIKE '%,none,%' THEN 'noindex'
        WHEN canonical_url IS NOT NULL AND canonical_url <> url THEN 'Canonicalised'
    END
    WHERE crawl_id = :crawl_id
    """
)
_INDEXABLE = sa.text("UPDATE pages SET indexable = indexability_status IS NULL WHERE crawl_id = :crawl_id")


def compute_indexability(conn: sa.Connection, crawl_id: int) -> None:
    """Fill pages.indexable / indexability_status — rules and reports rely on them."""
    conn.execute(_INDEXABILITY, {"crawl_id": crawl_id})
    conn.execute(_INDEXABLE, {"crawl_id": crawl_id})


def _run_sql(query: sa.TextClause) -> RuleFinder:
    def find(conn: sa.Connection, crawl_id: int, thresholds: ThresholdSettings) -> list[Finding]:
        params = {"crawl_id": crawl_id, **thresholds.model_dump()}  # thresholds bind as :title_max_chars etc.
        return [(url, detail) for url, detail in conn.execute(query, params)]

    return find


def _sql(where: str, detail: str = "NULL") -> RuleFinder:
    """A rule that is a filter over the crawl's pages; `where` may use thresholds as :name."""
    return _run_sql(sa.text(f"SELECT url, {detail} FROM pages WHERE crawl_id = :crawl_id AND ({where}) ORDER BY url"))  # noqa: S608 — fixed rule text, values are bound


def _duplicate(column: str) -> RuleFinder:
    """Pages whose `column` value is shared with another page (one pass: a window count per value)."""
    return _run_sql(
        sa.text(
            f"SELECT url, 'на ' || n || ' стр.: ' || value FROM ("  # noqa: S608 — fixed column name
            f"  SELECT url, {column} AS value, count(*) OVER (PARTITION BY {column}) AS n FROM pages"
            f"  WHERE crawl_id = :crawl_id AND {INDEXABLE_HTML} AND trim(coalesce({column}, '')) <> ''"
            ") WHERE n > 1 ORDER BY value, url"
        )
    )


def _length(column: str, op: str, threshold: str) -> RuleFinder:
    return _sql(
        f"{HTML_OK} AND trim(coalesce({column}, '')) <> '' AND length({column}) {op} :{threshold}",
        f"length({column}) || ' симв.: ' || {column}",
    )


def _onpage_rules() -> list[Rule]:
    def r(code, group, name, kind, priority, description, find) -> Rule:
        return Rule(code, group, f"{group}: {name}", kind, priority, description, find)

    missing = "trim(coalesce({c}, '')) = ''"
    return [
        # --- Page Titles
        r("page_title_missing", "Page Titles", "Missing", "issue", "high",
          "Нет <title>, он пустой или из пробелов.", _sql(f"{HTML_OK} AND {missing.format(c='title')}")),
        r("page_title_multiple", "Page Titles", "Multiple", "issue", "high",
          "На странице несколько <title>.", _sql(f"{HTML_OK} AND title_count > 1", "CAST(title_count AS TEXT)")),
        r("page_title_outside_head", "Page Titles", "Outside <head>", "issue", "high",
          "<title> стоит вне <head>: поисковик может его не учесть.", _sql(f"{HTML_OK} AND title_outside_head > 0")),
        r("page_title_duplicate", "Page Titles", "Duplicate", "opportunity", "medium",
          "Одинаковый title у нескольких страниц: поисковику трудно различить их.", _duplicate("title")),
        r("page_title_over_max", "Page Titles", "Over Max Characters", "opportunity", "medium",
          "Title длиннее thresholds.title_max_chars: может обрезаться в выдаче.",
          _length("title", ">", "title_max_chars")),
        r("page_title_below_min", "Page Titles", "Below Min Characters", "opportunity", "medium",
          "Title короче thresholds.title_min_chars: место в выдаче используется не полностью.",
          _length("title", "<", "title_min_chars")),
        r("page_title_same_as_h1", "Page Titles", "Same as H1", "opportunity", "low",
          "Title дословно совпадает с H1: упущена возможность раскрыть страницу иначе.",
          _sql(f"{HTML_OK} AND trim(coalesce(title, '')) <> '' AND title = h1", "title")),
        # --- Meta Description
        r("meta_description_multiple", "Meta Description", "Multiple", "issue", "medium",
          "Несколько meta description на странице.",
          _sql(f"{HTML_OK} AND meta_description_count > 1", "CAST(meta_description_count AS TEXT)")),
        r("meta_description_outside_head", "Meta Description", "Outside <head>", "issue", "medium",
          "Meta description вне <head>: поисковик может её проигнорировать.",
          _sql(f"{HTML_OK} AND meta_description_outside_head > 0")),
        r("meta_description_missing", "Meta Description", "Missing", "opportunity", "low",
          "Meta description нет, она пустая или из пробелов: сниппет поисковик соберёт сам.",
          _sql(f"{HTML_OK} AND {missing.format(c='meta_description')}")),
        r("meta_description_duplicate", "Meta Description", "Duplicate", "opportunity", "low",
          "Одинаковая meta description у нескольких страниц.", _duplicate("meta_description")),
        r("meta_description_over_max", "Meta Description", "Over Max Characters", "opportunity", "low",
          "Длиннее thresholds.description_max_chars: обрежется в сниппете.",
          _length("meta_description", ">", "description_max_chars")),
        r("meta_description_below_min", "Meta Description", "Below Min Characters", "opportunity", "low",
          "Короче thresholds.description_min_chars: сниппет можно сделать информативнее.",
          _length("meta_description", "<", "description_min_chars")),
        # --- H1
        r("h1_missing", "H1", "Missing", "issue", "medium",
          "Нет <h1>, он пустой или из пробелов.", _sql(f"{HTML_OK} AND {missing.format(c='h1')}")),
        r("h1_multiple", "H1", "Multiple", "warning", "medium",
          "Несколько <h1> на странице.", _sql(f"{HTML_OK} AND h1_count > 1", "CAST(h1_count AS TEXT)")),
        r("h1_alt_text", "H1", "Alt Text in h1", "warning", "low",
          "Текст H1 взят из alt картинки внутри <h1>: проверьте, что это осмысленный заголовок.",
          _sql(f"{HTML_OK} AND h1_from_alt", "h1")),
        r("h1_non_sequential", "H1", "Non-sequential", "warning", "low",
          "<h1> не первый заголовок на странице.", _sql(f"{HTML_OK} AND h1_count > 0 AND NOT h1_first_heading")),
        r("h1_duplicate", "H1", "Duplicate", "opportunity", "low",
          "Одинаковый H1 у нескольких страниц.", _duplicate("h1")),
        r("h1_over_max", "H1", "Over Max Characters", "opportunity", "low",
          "H1 длиннее thresholds.h1_max_chars.", _length("h1", ">", "h1_max_chars")),
        # --- H2
        r("h2_missing", "H2", "Missing", "warning", "low",
          "Нет <h2>, он пустой или из пробелов.", _sql(f"{HTML_OK} AND {missing.format(c='h2')}")),
        r("h2_multiple", "H2", "Multiple", "warning", "low",
          "Несколько <h2> (информационно: обычно это нормально).",
          _sql(f"{HTML_OK} AND h2_count > 1", "CAST(h2_count AS TEXT)")),
        r("h2_non_sequential", "H2", "Non-sequential", "warning", "low",
          "Первому <h2> предшествует не <h1>: уровни заголовков пропущены или перепутаны.",
          _sql(f"{HTML_OK} AND h2_count > 0 AND NOT h2_sequential")),
        r("h2_duplicate", "H2", "Duplicate", "opportunity", "low",
          "Одинаковый первый H2 у нескольких страниц.", _duplicate("h2")),
        r("h2_over_max", "H2", "Over Max Characters", "opportunity", "low",
          "H2 длиннее thresholds.h2_max_chars.", _length("h2", ">", "h2_max_chars")),
    ]  # fmt: skip


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


def _redirect_loops(conn: sa.Connection, crawl_id: int, _thresholds: ThresholdSettings) -> list[Finding]:
    graph = _redirect_graph(conn, crawl_id)
    found = []
    for url in sorted(graph):
        path, loops = _follow(graph, url)
        if loops:
            found.append((url, " → ".join(path)))
    return found


def _redirect_chains(conn: sa.Connection, crawl_id: int, thresholds: ThresholdSettings) -> list[Finding]:
    """Redirects that land on another redirect: `redirect_chain_hops`+ hops to the final URL (loops: own rule)."""
    graph = _redirect_graph(conn, crawl_id)
    found = []
    for url in sorted(graph):
        path, loops = _follow(graph, url)
        if not loops and len(path) - 1 >= thresholds.redirect_chain_hops:
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


def _directive(name: str) -> str:
    return f"robots_directives LIKE '%,{name},%'"


_NON_INDEXABLE_CANONICAL = _run_sql(
    sa.text(
        "SELECT p.url, p.canonical_url || ' — ' || t.indexability_status FROM pages p"
        " JOIN pages t ON t.crawl_id = p.crawl_id AND t.url = p.canonical_url"
        " WHERE p.crawl_id = :crawl_id AND p.canonical_url <> p.url AND NOT t.indexable ORDER BY p.url"  # self: see noindex
    )
)


def _directive_canonical_rules() -> list[Rule]:
    def r(code, group, name, kind, priority, description, find) -> Rule:
        return Rule(code, group, f"{group}: {name}", kind, priority, description, find)

    return [
        # --- Canonicals
        r("canonical_multiple_conflicting", "Canonicals", "Multiple Conflicting", "issue", "high",
          "Несколько canonical с разными URL (в HTML и/или заголовке Link): поисковик выберет сам.",
          _sql("canonical_conflict", "canonical_url")),
        r("canonical_non_indexable", "Canonicals", "Non-Indexable Canonical", "issue", "high",
          "Canonical ведёт на неиндексируемый URL (редирект, ошибка, noindex, запрет robots.txt…).",
          _NON_INDEXABLE_CANONICAL),
        r("canonical_invalid_attribute", "Canonicals", "Invalid Attribute In Annotation", "issue", "high",
          "У <link rel=\"canonical\"> лишние атрибуты hreflang, lang, media или type: поисковик может его не принять.",
          _sql("canonical_invalid_attr", "canonical_url")),
        r("canonical_fragment", "Canonicals", "Contains Fragment URL", "issue", "high",
          "Canonical содержит фрагмент #…: поисковики фрагмент отбрасывают, это признак ошибки.",
          _sql("canonical_fragment", "canonical_url")),
        r("canonical_outside_head", "Canonicals", "Outside <head>", "issue", "high",
          "<link rel=\"canonical\"> вне <head>: поисковик его проигнорирует.", _sql("canonical_outside_head > 0")),
        r("canonical_canonicalised", "Canonicals", "Canonicalised", "warning", "high",
          "Canonical указывает на другой URL: страница «склеена» с ним и сама не индексируется.",
          _sql("canonical_url IS NOT NULL AND canonical_url <> url", "canonical_url")),
        r("canonical_missing", "Canonicals", "Missing", "warning", "medium",
          "Canonical нет ни в HTML, ни в заголовке Link.", _sql(f"{HTML_OK} AND coalesce(canonical_count, 0) = 0")),
        r("canonical_multiple", "Canonicals", "Multiple", "warning", "low",
          "Несколько canonical (пусть и одинаковых).", _sql("canonical_count > 1", "CAST(canonical_count AS TEXT)")),
        r("canonical_relative", "Canonicals", "Canonical Is Relative", "warning", "low",
          "Canonical задан относительным URL: надёжнее абсолютный.", _sql("canonical_relative", "canonical_url")),
        # --- Directives
        r("directives_outside_head", "Directives", "Outside <head>", "issue", "high",
          "<meta name=\"robots\"> вне <head>: поисковик его проигнорирует.", _sql("robots_outside_head > 0")),
        r("directives_noimageindex", "Directives", "NoImageIndex", "issue", "low",
          "noimageindex: картинки страницы не попадут в поиск по картинкам.", _sql(_directive("noimageindex"))),
        r("directives_noindex", "Directives", "Noindex", "warning", "high",
          "noindex в meta robots или X-Robots-Tag: страница не попадёт в индекс.", _sql(_directive("noindex"))),
        r("directives_nofollow", "Directives", "Nofollow", "warning", "high",
          "nofollow: поисковик не пойдёт по ссылкам страницы.", _sql(_directive("nofollow"))),
        r("directives_none", "Directives", "None", "warning", "high",
          "none = noindex, nofollow: страницы нет в индексе и ссылки не учитываются.", _sql(_directive("none"))),
        r("directives_unavailable_after", "Directives", "Unavailable_After", "warning", "medium",
          "unavailable_after: страница выпадет из индекса после указанной даты.",
          _sql(_directive("unavailable_after"))),
        r("directives_nosnippet", "Directives", "NoSnippet", "warning", "low",
          "nosnippet: в выдаче не будет текстового сниппета.", _sql(_directive("nosnippet"))),
        r("directives_noodp", "Directives", "NoODP", "warning", "low",
          "noodp — устаревшая директива (каталог DMOZ закрыт), её можно убрать.", _sql(_directive("noodp"))),
        r("directives_noydir", "Directives", "NoYDIR", "warning", "low",
          "noydir — устаревшая директива (каталог Yahoo закрыт), её можно убрать.", _sql(_directive("noydir"))),
        r("directives_notranslate", "Directives", "NoTranslate", "warning", "low",
          "notranslate: поисковик не предложит перевод страницы.", _sql(_directive("notranslate"))),
    ]  # fmt: skip


RULES += _onpage_rules()
RULES += _directive_canonical_rules()
BY_CODE = {rule.code: rule for rule in RULES}
_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def rule(code: str) -> Rule:
    if code not in BY_CODE:
        raise InvalidArguments(f"Unknown issue code '{code}'. Known codes: {', '.join(BY_CODE)}.")
    return BY_CODE[code]


def analyze(engine: sa.Engine, crawl_id: int, thresholds: ThresholdSettings | None = None) -> int:
    """(Re)compute every rule for a crawl, replacing earlier findings. Returns the number of findings."""
    thresholds = thresholds or ThresholdSettings()
    with engine.begin() as conn:
        compute_indexability(conn, crawl_id)
        conn.execute(sa.delete(storage.issues).where(storage.issues.c.crawl_id == crawl_id))
        rows = [
            {"crawl_id": crawl_id, "code": r.code, "url": url, "detail": detail}
            for r in RULES
            for url, detail in r.find(conn, crawl_id, thresholds)
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
