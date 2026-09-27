"""SEO checks over a stored crawl: each rule turns crawl tables into (url, detail) findings.

Rules run after the crawl, never during it — memory stays flat, and `spider analyze` can
re-run them on an old crawl (new rules, changed thresholds) without fetching anything.
Most rules are one SQL query; the ones that need graph walking are Python. Codes, types and
priorities follow Screaming Frog's issue library (docs/features.md, docs/reference/).
"""

from __future__ import annotations

import base64
import logging
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

import sqlalchemy as sa
from pydantic import ValidationError

from . import duplicates as duplicates_module
from . import hreflang as hreflang_module
from . import pagination as pagination_module
from . import security as security_module
from . import serp as serp_module
from . import settings as settings_module
from . import sitemaps as sitemaps_module
from . import storage
from .errors import InvalidArguments
from .extract import anchor_hash
from .settings import Settings, ThresholdSettings

log = logging.getLogger(__name__)
Finding = tuple[str, str | None]  # (url, detail)
RuleFinder = Callable[[sa.Connection, int, ThresholdSettings], Iterable[Finding]]


@dataclass(frozen=True)
class Rule:
    code: str
    group: str
    name: str
    type: Literal["issue", "warning", "opportunity"]
    priority: Literal["high", "medium", "low"]
    description: str
    find: RuleFinder
    # settings keys (collect.*) that must have been on during the crawl, or `key=value` / `key!=value`
    requires: tuple[str, ...] = ()


# Rules look at the site's own URLs unless they say otherwise; on-page checks at the site's HTML pages
# that answered 200 and were read (not only checked); duplicates among indexable ones (thresholds.duplicates_indexable_only).
INTERNAL = "NOT coalesce(external, FALSE)"
EXTERNAL = "coalesce(external, FALSE)"
RENDERED = "crawl.render!=never"  # the JavaScript rules: pages were opened in a browser
HTML_OK = f"{INTERNAL} AND parsed AND status_code = 200 AND content_type LIKE '%html%'"
# on-page and content checks: HTML_OK, and indexable too while thresholds.issues_indexable_only
ONPAGE = f"{HTML_OK} AND (indexable OR NOT :issues_indexable_only)"

# Why a URL can't be indexed — Screaming Frog's Indexability Status, first matching reason wins.
_INDEXABILITY = sa.text(
    """
    UPDATE pages SET indexability_status = CASE
        WHEN blocked = 'robots_txt' THEN 'Blocked by Robots.txt'
        WHEN status_code = 0 THEN 'No Response'
        WHEN status_code BETWEEN 300 AND 399 THEN 'Redirected'
        WHEN refresh_url IS NOT NULL AND (refresh_url <> url OR :self_refresh_non_indexable) THEN 'Redirected'
        WHEN status_code BETWEEN 400 AND 499 THEN 'Client Error'
        WHEN status_code >= 500 THEN 'Server Error'
        WHEN robots_directives LIKE '%,noindex,%' OR robots_directives LIKE '%,none,%' THEN 'noindex'
        WHEN canonical_url IS NOT NULL AND canonical_url <> url THEN 'Canonicalised'
    END
    WHERE crawl_id = :crawl_id
    """
)
_INDEXABLE = sa.text("UPDATE pages SET indexable = indexability_status IS NULL WHERE crawl_id = :crawl_id")


def compute_indexability(conn: sa.Connection, crawl_id: int, thresholds: ThresholdSettings | None = None) -> None:
    """Fill pages.indexable / indexability_status — rules and reports rely on them.

    A refresh to the page itself counts as a redirect while thresholds.self_refresh_non_indexable (default).
    """
    self_refresh = (thresholds or ThresholdSettings()).self_refresh_non_indexable
    conn.execute(_INDEXABILITY, {"crawl_id": crawl_id, "self_refresh_non_indexable": self_refresh})
    conn.execute(_INDEXABLE, {"crawl_id": crawl_id})


# Link counts per page from the site's own <a href> links: one grouped pass over link_rows each (by URL id,
# in index order), then the URL text for the few thousand groups — not a query per page, and no sort of
# millions of URL strings. UPDATE … FROM needs SQLite 3.33+.
_LINK_COUNTS = [
    "UPDATE pages SET inlinks = 0, unique_inlinks = 0, unique_outlinks = 0 WHERE crawl_id = :crawl_id",
    "UPDATE pages SET inlinks = s.n, unique_inlinks = s.u FROM (SELECT u.url, g.n, g.u FROM (SELECT target_id,"
    " count(*) AS n, count(DISTINCT source_id) AS u FROM link_rows WHERE crawl_id = :crawl_id AND kind = 'hyperlink'"
    " AND internal GROUP BY target_id) AS g JOIN urls u ON u.id = g.target_id) AS s"
    " WHERE pages.crawl_id = :crawl_id AND pages.url = s.url",
    "UPDATE pages SET unique_outlinks = s.u FROM (SELECT u.url, g.u FROM (SELECT source_id,"
    " count(DISTINCT target_id) AS u FROM link_rows WHERE crawl_id = :crawl_id AND kind = 'hyperlink' AND internal"
    " GROUP BY source_id) AS g JOIN urls u ON u.id = g.source_id) AS s"
    " WHERE pages.crawl_id = :crawl_id AND pages.url = s.url",
]


def compute_link_counts(conn: sa.Connection, crawl_id: int) -> None:
    for statement in _LINK_COUNTS:
        conn.execute(sa.text(statement), {"crawl_id": crawl_id})


@dataclass(frozen=True)
class SqlFinder:
    """A rule that is one `SELECT url, detail`; thresholds bind as :title_max_chars etc.

    `analyze` doesn't read its findings into Python: `store` copies them inside SQLite — a crawl where
    every page has several issues would otherwise hold them all in memory at once.
    """

    query: sa.TextClause

    def __call__(self, conn: sa.Connection, crawl_id: int, thresholds: ThresholdSettings) -> list[Finding]:
        return [(url, detail) for url, detail in conn.execute(self.query, self._params(crawl_id, thresholds))]

    def store(self, conn: sa.Connection, crawl_id: int, code: str, thresholds: ThresholdSettings) -> int:
        insert = sa.text(
            f"INSERT INTO issues (crawl_id, code, url, detail) SELECT :crawl_id, :rule_code, * FROM ({self.query.text})"  # noqa: S608 — fixed rule text
        )
        return conn.execute(insert, self._params(crawl_id, thresholds) | {"rule_code": code}).rowcount

    @staticmethod
    def _params(crawl_id: int, thresholds: ThresholdSettings) -> dict:
        return {"crawl_id": crawl_id, **thresholds.model_dump()}


def _run_sql(query: sa.TextClause) -> RuleFinder:
    return SqlFinder(query)


def _sql(where: str, detail: str = "NULL", *, external: bool = False) -> RuleFinder:
    """A rule that is a filter over the crawl's pages (the site's own, or `external` ones); thresholds bind as :name."""
    among = EXTERNAL if external else INTERNAL
    return _run_sql(
        sa.text(f"SELECT url, {detail} FROM pages WHERE crawl_id = :crawl_id AND {among} AND ({where}) ORDER BY url")  # noqa: S608 — fixed rule text, values are bound
    )


def _duplicate(column: str, *, skip_paginated: bool = True) -> RuleFinder:
    """Pages whose `column` value is shared with another page (one pass: a window count per value).

    Among the site's HTML pages — indexable ones only while thresholds.duplicates_indexable_only; `skip_paginated`
    — pages 2+ of a rel next/prev series are left out while thresholds.ignore_paginated_duplicates says so: a
    list's pages share their title and headings by design.
    """
    among = f"{HTML_OK} AND (indexable OR NOT :duplicates_indexable_only)"
    paginated = " AND NOT (:ignore_paginated_duplicates AND coalesce(pagination, '') = 'paginated')"
    return _run_sql(
        sa.text(
            f"SELECT url, 'на ' || n || ' стр.: ' || value FROM ("  # noqa: S608 — fixed column and filter
            f"  SELECT url, {column} AS value, count(*) OVER (PARTITION BY {column}) AS n FROM pages"
            f"  WHERE crawl_id = :crawl_id AND {among} AND trim(coalesce({column}, '')) <> ''"
            f"{paginated if skip_paginated else ''}"
            ") WHERE n > 1 ORDER BY value, url"
        )
    )


def _length(column: str, op: str, threshold: str) -> RuleFinder:
    return _sql(
        f"{ONPAGE} AND trim(coalesce({column}, '')) <> '' AND length({column}) {op} :{threshold}",
        f"length({column}) || ' симв.: ' || {column}",
    )


def _onpage_rules() -> list[Rule]:
    def r(code, group, name, kind, priority, description, find) -> Rule:
        return Rule(code, group, f"{group}: {name}", kind, priority, description, find)

    missing = "trim(coalesce({c}, '')) = ''"
    return [
        # --- Page Titles
        r("page_title_missing", "Page Titles", "Missing", "issue", "high",
          "Нет <title>, он пустой или из пробелов.", _sql(f"{ONPAGE} AND {missing.format(c='title')}")),
        r("page_title_multiple", "Page Titles", "Multiple", "issue", "high",
          "На странице несколько <title>.", _sql(f"{ONPAGE} AND title_count > 1", "CAST(title_count AS TEXT)")),
        r("page_title_outside_head", "Page Titles", "Outside <head>", "issue", "high",
          "<title> стоит вне <head>: поисковик может его не учесть.", _sql(f"{ONPAGE} AND title_outside_head > 0")),
        r("page_title_duplicate", "Page Titles", "Duplicate", "opportunity", "medium",
          "Одинаковый title у нескольких страниц: поисковику трудно различить их.", _duplicate("title")),
        r("page_title_over_max", "Page Titles", "Over Max Characters", "opportunity", "medium",
          "Title длиннее thresholds.title_max_chars: может обрезаться в выдаче.",
          _length("title", ">", "title_max_chars")),
        r("page_title_below_min", "Page Titles", "Below Min Characters", "opportunity", "medium",
          "Title короче thresholds.title_min_chars: место в выдаче используется не полностью.",
          _length("title", "<", "title_min_chars")),
        r("page_title_over_px", "Page Titles", "Over Max Pixels", "opportunity", "medium",
          "Title шире thresholds.title_max_px пикселей (Arial 20px): обрежется в выдаче Google.",
          _sql(f"{ONPAGE} AND title_px > :title_max_px", "title_px || ' px: ' || title")),
        r("page_title_below_px", "Page Titles", "Below Min Pixels", "opportunity", "medium",
          "Title уже thresholds.title_min_px пикселей: место в выдаче используется не полностью.",
          _sql(f"{ONPAGE} AND title_px < :title_min_px", "title_px || ' px: ' || title")),
        r("page_title_same_as_h1", "Page Titles", "Same as H1", "opportunity", "low",
          "Title дословно совпадает с H1: упущена возможность раскрыть страницу иначе.",
          _sql(f"{ONPAGE} AND trim(coalesce(title, '')) <> '' AND title = h1", "title")),
        # --- Meta Description
        r("meta_description_multiple", "Meta Description", "Multiple", "issue", "medium",
          "Несколько meta description на странице.",
          _sql(f"{ONPAGE} AND meta_description_count > 1", "CAST(meta_description_count AS TEXT)")),
        r("meta_description_outside_head", "Meta Description", "Outside <head>", "issue", "medium",
          "Meta description вне <head>: поисковик может её проигнорировать.",
          _sql(f"{ONPAGE} AND meta_description_outside_head > 0")),
        r("meta_description_missing", "Meta Description", "Missing", "opportunity", "low",
          "Meta description нет, она пустая или из пробелов: сниппет поисковик соберёт сам.",
          _sql(f"{ONPAGE} AND {missing.format(c='meta_description')}")),
        r("meta_description_duplicate", "Meta Description", "Duplicate", "opportunity", "low",
          "Одинаковая meta description у нескольких страниц.", _duplicate("meta_description")),
        r("meta_description_over_max", "Meta Description", "Over Max Characters", "opportunity", "low",
          "Длиннее thresholds.description_max_chars: обрежется в сниппете.",
          _length("meta_description", ">", "description_max_chars")),
        r("meta_description_below_min", "Meta Description", "Below Min Characters", "opportunity", "low",
          "Короче thresholds.description_min_chars: сниппет можно сделать информативнее.",
          _length("meta_description", "<", "description_min_chars")),
        r("meta_description_over_px", "Meta Description", "Over Max Pixels", "opportunity", "low",
          "Description шире thresholds.description_max_px пикселей (Arial 14px): обрежется в сниппете.",
          _sql(f"{ONPAGE} AND description_px > :description_max_px", "description_px || ' px'")),
        r("meta_description_below_px", "Meta Description", "Below Min Pixels", "opportunity", "low",
          "Description уже thresholds.description_min_px пикселей: сниппет можно сделать информативнее.",
          _sql(f"{ONPAGE} AND description_px < :description_min_px", "description_px || ' px'")),
        # --- H1
        r("h1_missing", "H1", "Missing", "issue", "medium",
          "Нет <h1>, он пустой или из пробелов.", _sql(f"{ONPAGE} AND {missing.format(c='h1')}")),
        r("h1_multiple", "H1", "Multiple", "warning", "medium",
          "Несколько <h1> на странице.", _sql(f"{ONPAGE} AND h1_count > 1", "CAST(h1_count AS TEXT)")),
        r("h1_alt_text", "H1", "Alt Text in h1", "warning", "low",
          "Текст H1 взят из alt картинки внутри <h1>: проверьте, что это осмысленный заголовок.",
          _sql(f"{ONPAGE} AND h1_from_alt", "h1")),
        r("h1_non_sequential", "H1", "Non-sequential", "warning", "low",
          "<h1> не первый заголовок на странице.", _sql(f"{ONPAGE} AND h1_count > 0 AND NOT h1_first_heading")),
        r("h1_duplicate", "H1", "Duplicate", "opportunity", "low",
          "Одинаковый H1 у нескольких страниц.", _duplicate("h1")),
        r("h1_over_max", "H1", "Over Max Characters", "opportunity", "low",
          "H1 длиннее thresholds.h1_max_chars.", _length("h1", ">", "h1_max_chars")),
        # --- H2
        r("h2_missing", "H2", "Missing", "warning", "low",
          "Нет <h2>, он пустой или из пробелов.", _sql(f"{ONPAGE} AND {missing.format(c='h2')}")),
        r("h2_multiple", "H2", "Multiple", "warning", "low",
          "Несколько <h2> (информационно: обычно это нормально).",
          _sql(f"{ONPAGE} AND h2_count > 1", "CAST(h2_count AS TEXT)")),
        r("h2_non_sequential", "H2", "Non-sequential", "warning", "low",
          "Первому <h2> предшествует не <h1>: уровни заголовков пропущены или перепутаны.",
          _sql(f"{ONPAGE} AND h2_count > 0 AND NOT h2_sequential")),
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
        .where(sa.not_(sa.func.coalesce(storage.pages.c.external, False)))
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
    Rule(
        "internal_redirection_javascript",
        "Response Codes",
        "Internal Redirection (JavaScript)",
        "warning",
        "low",
        "Страница уводит на другой URL скриптом (location…): такой редирект видно только после рендеринга, "
        "поисковик может его не выполнить — лучше серверный 301.",
        _sql("refresh_kind = 'javascript'", "refresh_url"),
        (RENDERED,),
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


def _soft_404(conn: sa.Connection, crawl_id: int, thresholds: ThresholdSettings) -> Iterable[Finding]:
    """200 pages whose title or H1 reads like an error page (thresholds.soft_404_patterns), streamed."""
    patterns = [re.compile(p, re.IGNORECASE) for p in thresholds.soft_404_patterns]
    if not patterns:
        return
    rows = storage.streamed(conn, 1000).execute(
        sa.text(f"SELECT url, title, h1 FROM pages WHERE crawl_id = :crawl_id AND {ONPAGE} ORDER BY url"),  # noqa: S608
        {"crawl_id": crawl_id, "issues_indexable_only": thresholds.issues_indexable_only},
    )
    for url, title, h1 in rows:
        for text in (title, h1):
            if text and any(p.search(text) for p in patterns):
                yield url, text
                break


def _readability(low: str, high: str | None) -> RuleFinder:
    band = f"flesch < :{low}" + (f" AND flesch >= :{high}" if high else "")
    return _sql(f"{ONPAGE} AND word_count >= :readability_min_words AND {band}",
                "'индекс Флеша ' || flesch || ', слов в предложении ' || words_per_sentence")  # fmt: skip


def _content_rules() -> list[Rule]:
    def r(code, name, kind, priority, description, find, requires=()) -> Rule:
        return Rule(code, "Content", f"Content: {name}", kind, priority, description, find, requires)

    return [
        r("content_exact_duplicates", "Exact Duplicates", "issue", "high",
          "Страница побайтно совпадает с другой (одинаковый md5 HTML): дубль под разными URL.",
          _duplicate("content_md5", skip_paginated=False)),
        r("content_soft_404", "Soft 404 Pages", "warning", "high",
          "Страница отвечает 200, но по title / H1 — «страница не найдена» (thresholds.soft_404_patterns): "
          "поисковик сочтёт её ошибкой, а обход — рабочей.", _soft_404),
        r("content_lorem_ipsum", "Lorem Ipsum Placeholder", "warning", "high",
          "На странице остался текст-заглушка «Lorem ipsum».", _sql(f"{ONPAGE} AND lorem_ipsum")),
        r("content_near_duplicates", "Near Duplicates", "warning", "medium",
          "Текст почти совпадает с другой страницей (сходство MinHash ≥ thresholds.near_duplicate_similarity): "
          "пары — `spider duplicates`.",
          _run_sql(sa.text(duplicates_module.PAIRS + duplicates_module.NEAR_FINDINGS)), ("collect.near_duplicates",)),
        r("content_low_content", "Low Content Pages", "opportunity", "medium",
          "Мало текста: меньше thresholds.low_content_words слов в видимом тексте.",
          _sql(f"{ONPAGE} AND word_count < :low_content_words", "word_count || ' слов'")),
        r("content_readability_difficult", "Readability Difficult", "opportunity", "low",
          "Текст трудно читать: индекс Флеша ниже thresholds.readability_difficult (длинные предложения и слова).",
          _readability("readability_difficult", "readability_very_difficult")),
        r("content_readability_very_difficult", "Readability Very Difficult", "opportunity", "low",
          "Текст очень трудно читать: индекс Флеша ниже thresholds.readability_very_difficult.",
          _readability("readability_very_difficult", None)),
    ]  # fmt: skip


STORE_INTERNAL = "collect.internal_links.store"
STORE_EXTERNAL = "collect.external_links.store"
FOLLOW_EXTERNAL = "collect.external_links.follow"
STORE_CANONICALS = "collect.canonicals.store"
HYPERLINK = "crawl_id = :crawl_id AND kind = 'hyperlink'"
_LOCALHOST = " OR ".join(
    f"target LIKE '{scheme}://{host}%'" for scheme in ("http", "https") for host in ("localhost", "127.", "[::1]")
)


def _by_target(detail: str, where: str, having: str = "TRUE") -> str:
    """Link rows grouped by target: aggregated over URL ids (index order, no string sort), reported by URL."""
    return (
        f"SELECT u.url, g.detail FROM (SELECT target_id, {detail} AS detail FROM link_rows"  # noqa: S608 — fixed rule text
        f" WHERE crawl_id = :crawl_id AND {where} GROUP BY target_id HAVING {having}) AS g"
        " JOIN urls u ON u.id = g.target_id ORDER BY u.url"
    )


def _links_sql(query: str) -> RuleFinder:
    return _run_sql(sa.text(query))


def _non_descriptive(conn: sa.Connection, crawl_id: int, thresholds: ThresholdSettings) -> list[Finding]:
    anchors = [a.strip().casefold() for a in thresholds.non_descriptive_anchors]
    if not anchors:
        return []
    query = sa.text(
        f"SELECT source, count(*) || ' шт., например «' || min(anchor) || '»' FROM links WHERE {HYPERLINK}"  # noqa: S608 — fixed text
        " AND internal AND casefold(trim(anchor)) IN :anchors GROUP BY source ORDER BY source"
    ).bindparams(sa.bindparam("anchors", expanding=True))
    return [(url, detail) for url, detail in conn.execute(query, {"crawl_id": crawl_id, "anchors": anchors})]


def _link_rules() -> list[Rule]:
    def r(code, name, kind, priority, description, find, requires=()) -> Rule:
        return Rule(code, "Links", f"Links: {name}", kind, priority, description, find, requires)

    def ext(code, name, description, where, requires=(FOLLOW_EXTERNAL,)) -> Rule:
        return Rule(
            code,
            "Response Codes",
            name,
            "warning",
            "low",
            description,
            _sql(where, "CAST(status_code AS TEXT) || coalesce(': ' || error, '')", external=True),
            requires,
        )

    return [
        r("links_outlinks_to_localhost", "Outlinks To Localhost", "issue", "high",
          "Ссылки на localhost / 127.0.0.1: на сайте они никуда не ведут, это следы разработки.",
          _links_sql(f"SELECT source, group_concat(DISTINCT target) FROM links WHERE {HYPERLINK} AND NOT internal"  # noqa: S608
                     f" AND ({_LOCALHOST}) GROUP BY source ORDER BY source"), (STORE_EXTERNAL,)),
        r("links_uncrawlable_outlinks", "Pages With Uncrawlable Internal Outlinks", "warning", "high",
          "«Ссылки», по которым поисковик не перейдёт: javascript:, href не у <a>, переход в onclick.",
          _sql(f"{HTML_OK} AND uncrawlable_outlinks > 0", "uncrawlable_outlinks || ' шт.'")),
        r("links_no_internal_outlinks", "Pages Without Internal Outlinks", "warning", "high",
          "На странице нет ни одной внутренней follow-ссылки: тупик для поисковика и пользователя.",
          _sql(f"{HTML_OK} AND coalesce(internal_outlinks, 0) = 0")),
        r("links_non_indexable_inlinks_only", "Non-Indexable Page Inlinks Only", "warning", "high",
          "На индексируемую страницу ссылаются только неиндексируемые: поисковик может её не найти.",
          _links_sql(
              "SELECT t.url, NULL FROM pages t WHERE t.crawl_id = :crawl_id AND NOT coalesce(t.external, FALSE)"
              " AND t.indexable"
              " AND EXISTS (SELECT 1 FROM links l WHERE l.crawl_id = t.crawl_id AND l.target = t.url"
              "   AND l.kind = 'hyperlink')"
              " AND NOT EXISTS (SELECT 1 FROM links l JOIN pages s ON s.crawl_id = l.crawl_id AND s.url = l.source"
              "   WHERE l.crawl_id = t.crawl_id AND l.target = t.url AND l.kind = 'hyperlink' AND s.indexable)"
              " ORDER BY t.url"), (STORE_INTERNAL,)),
        r("links_internal_nofollow_outlinks", "Internal Nofollow Outlinks", "warning", "low",
          "Внутренние ссылки с rel=\"nofollow\": поисковик не передаёт по ним вес.",
          _sql(f"{HTML_OK} AND internal_nofollow_outlinks > 0", "internal_nofollow_outlinks || ' шт.'")),
        r("links_high_external_outlinks", "Pages With High External Outlinks", "warning", "low",
          "Внешних follow-ссылок больше thresholds.external_outlinks.",
          _sql(f"{HTML_OK} AND external_outlinks > :external_outlinks", "external_outlinks || ' шт.'")),
        r("links_high_internal_outlinks", "Pages With High Internal Outlinks", "warning", "low",
          "Внутренних follow-ссылок больше thresholds.internal_outlinks.",
          _sql(f"{HTML_OK} AND internal_outlinks > :internal_outlinks", "internal_outlinks || ' шт.'")),
        r("links_follow_and_nofollow_inlinks", "Follow & Nofollow Internal Inlinks To Page", "warning", "low",
          "На страницу ведут и follow-, и nofollow-ссылки: сигналы противоречат друг другу.",
          _links_sql(_by_target("sum(nofollow) || ' nofollow из ' || count(*)", "kind = 'hyperlink' AND internal",
                                "sum(nofollow) > 0 AND sum(NOT nofollow) > 0")),
          (STORE_INTERNAL,)),
        r("links_nofollow_inlinks_only", "Internal Nofollow Inlinks Only", "warning", "low",
          "На страницу ведут только nofollow-ссылки: поисковик может её не обойти.",
          _links_sql(_by_target("count(*) || ' шт.'", "kind = 'hyperlink' AND internal", "sum(NOT nofollow) = 0")),
          (STORE_INTERNAL,)),
        r("links_high_crawl_depth", "Pages With High Crawl Depth", "opportunity", "medium",
          "Страница в thresholds.crawl_depth и более кликах от старта: поисковику и людям до неё далеко.",
          _sql(f"{HTML_OK} AND depth >= :crawl_depth", "depth || ' кликов'")),
        r("links_no_anchor_text", "Internal Outlinks With No Anchor Text", "opportunity", "low",
          "Внутренние ссылки без текста (и картинки-ссылки без alt): поисковик не знает, о чём цель.",
          _links_sql(f"SELECT source, count(*) || ' шт.' FROM links WHERE {HYPERLINK} AND internal"  # noqa: S608
                     " AND trim(coalesce(anchor, '')) = '' AND trim(coalesce(alt, '')) = ''"
                     " GROUP BY source ORDER BY source"), (STORE_INTERNAL,)),
        r("links_non_descriptive_anchor", "Non-Descriptive Anchor Text In Internal Outlinks", "opportunity", "low",
          "Анкоры вроде «подробнее», «здесь» (thresholds.non_descriptive_anchors) ничего не говорят о цели.",
          _non_descriptive, (STORE_INTERNAL,)),
        # --- external URLs (checked, not crawled)
        ext("external_no_response", "External No Response", "Внешняя ссылка не ответила: таймаут, нет домена, отказ.",
            "status_code = 0"),
        ext("external_client_error", "External Client Error (4XX)", "Внешняя ссылка отдаёт 4xx — битая.",
            "status_code BETWEEN 400 AND 499"),
        ext("external_server_error", "External Server Error (5XX)", "Внешняя ссылка отдаёт 5xx.",
            "status_code >= 500"),
        # --- canonical discovery
        Rule("canonical_unlinked", "Canonicals", "Canonicals: Unlinked", "warning", "medium",
             "URL найден только через canonical: обычные ссылки на него не ведут.",
             _links_sql(
                 "SELECT t.url, NULL FROM pages t WHERE t.crawl_id = :crawl_id AND NOT coalesce(t.external, FALSE)"
                 " AND EXISTS (SELECT 1 FROM links l WHERE l.crawl_id = t.crawl_id AND l.target = t.url"
                 "   AND l.kind = 'canonical')"
                 " AND NOT EXISTS (SELECT 1 FROM links l WHERE l.crawl_id = t.crawl_id AND l.target = t.url"
                 "   AND l.kind = 'hyperlink') ORDER BY t.url"),
             (STORE_INTERNAL, STORE_CANONICALS)),
    ]  # fmt: skip


# --- URL: checks of the address itself. One Python pass after the crawl writes the flags a URL fails into
# pages.url_issues (",uppercase,parameters,"), the rules are then plain SQL filters — thresholds included,
# so `spider analyze` re-applies them to an old crawl.
URL_PAGES = "parsed"  # the site's crawled URLs (pages, redirects, errors), not resources or other sites
_URL_BATCH = 5000
_HEX = re.compile(r"%[0-9a-fA-F]{2}")
_GA_PARAM = re.compile(r"^(utm_[a-z_]+|_ga|_gl)$", re.IGNORECASE)


def url_issue_flags(url: str, internal_search: list[re.Pattern]) -> str | None:
    """The URL checks `url` fails, as ",flag,flag," (None — none): what `url_issues` stores."""
    parts = urlsplit(url)
    local = url[len(parts.scheme) + 3 + len(parts.netloc) :]  # path and query: the host is case-insensitive
    segments = [s for s in parts.path.split("/") if s and not s.isdigit()]
    checks = {
        "multiple_slashes": "//" in parts.path,
        "space": " " in url or "%20" in url,
        "non_ascii": not url.isascii(),
        "uppercase": any(c.isupper() for c in _HEX.sub("", local)),  # %D0 is encoding, not an uppercase letter
        "repetitive_path": len(segments) != len(set(segments)),
        "internal_search": any(p.search(local) for p in internal_search),
        "parameters": bool(parts.query),
        "ga_tracking": any(_GA_PARAM.match(p.partition("=")[0]) for p in parts.query.split("&")),
        "underscores": "_" in parts.path,
    }
    flags = [name for name, failed in checks.items() if failed]
    return f",{','.join(flags)}," if flags else None


def compute_url_issues(conn: sa.Connection, crawl_id: int, thresholds: ThresholdSettings) -> None:
    """Fill pages.url_issues for the site's crawled URLs, a batch at a time (memory stays flat)."""
    conn.execute(sa.text("UPDATE pages SET url_issues = NULL WHERE crawl_id = :crawl_id"), {"crawl_id": crawl_id})
    search = [re.compile(p, re.IGNORECASE) for p in thresholds.internal_search]
    select = sa.text(
        f"SELECT url FROM pages WHERE crawl_id = :crawl_id AND {INTERNAL} AND {URL_PAGES}"  # noqa: S608 — fixed text
        " AND url > :after ORDER BY url LIMIT :limit"
    )
    update = sa.text("UPDATE pages SET url_issues = :flags WHERE crawl_id = :crawl_id AND url = :url")
    after = ""
    while urls := conn.execute(select, {"crawl_id": crawl_id, "after": after, "limit": _URL_BATCH}).scalars().all():
        rows = [{"crawl_id": crawl_id, "url": url, "flags": flags} for url in urls
                if (flags := url_issue_flags(url, search))]  # fmt: skip
        if rows:
            conn.execute(update, rows)
        after = urls[-1]


def _broken_bookmarks(conn: sa.Connection, crawl_id: int, _thresholds: ThresholdSettings) -> Iterable[Finding]:
    """Pages linked to with a #fragment that names no id / <a name> on them (by the page's fingerprints)."""
    query = sa.text(
        "SELECT t.url, p.anchor_ids, l.fragment, count(*), min(s.url) FROM link_rows l"
        " JOIN urls t ON t.id = l.target_id JOIN urls s ON s.id = l.source_id"
        " JOIN pages p ON p.crawl_id = l.crawl_id AND p.url = t.url"
        " WHERE l.crawl_id = :crawl_id AND l.kind = 'hyperlink' AND l.internal AND l.fragment IS NOT NULL"
        " AND p.status_code = 200 AND p.anchor_ids IS NOT NULL"
        " GROUP BY t.url, p.anchor_ids, l.fragment ORDER BY t.url, l.fragment"
    )
    current: str | None = None
    broken: list[tuple[str, int, str]] = []

    def finding() -> Finding:
        links = sum(n for _, n, _ in broken)
        names = ", ".join(f"#{fragment}" for fragment, _, _ in broken)
        return current or "", f"{names} — {links} ссылк., например с {broken[0][2]}"

    for url, ids, fragment, n, example in conn.execute(query, {"crawl_id": crawl_id}):
        if url != current:
            if broken:
                yield finding()
            current, broken = url, []
        raw = base64.b64decode(ids)
        present = {raw[i : i + 2] for i in range(0, len(raw), 2)}
        if anchor_hash(fragment) not in present:
            broken.append((fragment, n, example))
    if broken:
        yield finding()


def _url_rules() -> list[Rule]:
    def r(code, name, kind, description, flag=None, find=None, requires=()) -> Rule:
        find = find or _sql(
            f"{URL_PAGES} AND url_issues LIKE '%,{flag},%'",
            "substr(url, instr(url, '?') + 1)" if flag in ("parameters", "ga_tracking") else "NULL",
        )
        return Rule(code, "URL", f"URL: {name}", kind, "low", description, find, requires)  # fmt: skip

    return [
        r("url_multiple_slashes", "Multiple Slashes", "issue",
          "В пути несколько слешей подряд (/page//): обычно ошибка шаблона, дубль адреса.", "multiple_slashes"),
        r("url_contains_space", "Contains A Space", "issue",
          "В URL пробел (или %20): такие ссылки ломаются при пересылке; разделяйте слова дефисом.", "space"),
        r("url_broken_bookmark", "Broken Bookmark", "issue",
          "Ссылка ведёт на якорь #id, которого нет на целевой странице: переход не прокрутит к нужному месту.",
          find=_broken_bookmarks, requires=(STORE_INTERNAL,)),
        r("url_non_ascii", "Non ASCII Characters", "warning",
          "В URL символы вне ASCII (кириллица и т.п.) без %-кодирования: не все клиенты передают их одинаково.",
          "non_ascii"),
        r("url_uppercase", "Uppercase", "warning",
          "В URL заглавные буквы: адреса чувствительны к регистру, легко получить дубль.", "uppercase"),
        r("url_repetitive_path", "Repetitive Path", "warning",
          "Сегмент пути повторяется (/shoes/shoes/): признак ошибки в относительных ссылках.", "repetitive_path"),
        r("url_internal_search", "Internal Search", "warning",
          "URL похож на страницу внутреннего поиска (thresholds.internal_search): их обычно закрывают от индекса.",
          "internal_search"),
        r("url_parameters", "Parameters", "warning",
          "URL с GET-параметрами (?, &): риск дублей и лишнего обхода.", "parameters"),
        r("url_ga_tracking", "GA Tracking Parameters", "warning",
          "В URL метки аналитики (utm_*, _ga, _gl): внутренние ссылки с метками плодят дубли.", "ga_tracking"),
        r("url_underscores", "Underscores", "opportunity",
          "Подчёркивания в пути: поисковики не всегда считают их разделителем слов, лучше дефис.", "underscores"),
        r("url_over_max", "Over Max Characters", "opportunity",
          "URL длиннее thresholds.url_max_chars: короткие адреса удобнее людям.",
          find=_sql(f"{URL_PAGES} AND length(url) > :url_max_chars", "length(url) || ' симв.'")),
    ]  # fmt: skip


# --- Hreflang: annotations are link rows of kind "hreflang" (partial indexes by source and by target).
STORE_HREFLANG = "collect.hreflang.store"
FOLLOW_HREFLANG = "collect.hreflang.follow"


def _hreflang_by_page(filter_name: str, detail: str, report_target: bool = False) -> RuleFinder:
    """Annotations passing one of the report's filters, one finding per page (the annotating page, or the target)."""
    page = "t.url" if report_target else "s.url"
    return _links_sql(
        f"SELECT {page}, group_concat({detail}, '; ') FROM link_rows l"  # noqa: S608 — fixed rule text
        " JOIN urls s ON s.id = l.source_id JOIN urls t ON t.id = l.target_id"
        " LEFT JOIN pages p ON p.crawl_id = l.crawl_id AND p.url = t.url"
        f" WHERE l.crawl_id = :crawl_id AND l.kind = 'hreflang' AND ({hreflang_module.FILTERS[filter_name]})"
        f" GROUP BY {page} ORDER BY {page}"
    )


def _hreflang_codes(conn: sa.Connection, crawl_id: int, _thresholds: ThresholdSettings) -> Iterable[Finding]:
    """Pages using codes that aren't ISO 639-1 [+ ISO 3166-1 alpha-2]: the distinct codes are few, checked once."""
    codes = conn.execute(
        sa.text("SELECT DISTINCT hreflang FROM link_rows WHERE crawl_id = :crawl_id AND kind = 'hreflang'"),
        {"crawl_id": crawl_id},
    ).scalars()
    invalid = sorted(code for code in codes if not hreflang_module.valid_code(code))
    if not invalid:
        return []
    query = sa.text(
        "SELECT s.url, group_concat(DISTINCT l.hreflang) FROM link_rows l JOIN urls s ON s.id = l.source_id"
        " WHERE l.crawl_id = :crawl_id AND l.kind = 'hreflang' AND l.hreflang IN :codes GROUP BY s.url ORDER BY s.url"
    ).bindparams(sa.bindparam("codes", expanding=True))
    return [(url, used) for url, used in conn.execute(query, {"crawl_id": crawl_id, "codes": invalid})]


_ANNOTATING = "SELECT DISTINCT source_id FROM link_rows WHERE crawl_id = :crawl_id AND kind = 'hreflang'"


def _hreflang_pages(where: str, detail: str = "NULL") -> RuleFinder:
    """Pages with hreflang annotations (`h.source_id`, `s.url`, `p` — its page row) matching `where`."""
    return _links_sql(
        f"SELECT s.url, {detail} FROM ({_ANNOTATING}) h JOIN urls s ON s.id = h.source_id"  # noqa: S608 — fixed text
        " JOIN pages p ON p.crawl_id = :crawl_id AND p.url = s.url"
        f" WHERE {where} ORDER BY s.url"
    )


def _annotates(target: str, extra: str = "") -> str:
    """The page (h.source_id) has an annotation pointing at `target` (a urls.id expression)."""
    return (
        "EXISTS (SELECT 1 FROM link_rows a WHERE a.crawl_id = :crawl_id AND a.kind = 'hreflang'"  # noqa: S608
        f" AND a.source_id = h.source_id AND a.target_id = {target}{extra})"
    )


_CANONICAL_ID = "(SELECT c.id FROM urls c WHERE c.crawl_id = :crawl_id AND c.url = p.canonical_url)"


def _hreflang_rules() -> list[Rule]:
    def r(code, name, kind, priority, description, find, requires=(STORE_HREFLANG,)) -> Rule:
        return Rule(code, "Hreflang", f"Hreflang: {name}", kind, priority, description, find, requires)

    return [
        r("hreflang_non_200", "Non-200 Hreflang URLs", "issue", "high",
          "Альтернативный URL из hreflang отвечает не 200: редирект, ошибка, запрет robots.txt, нет ответа.",
          _hreflang_by_page("non_200", "t.url || ' — ' || coalesce(p.blocked, CAST(p.status_code AS TEXT))"),
          (STORE_HREFLANG, FOLLOW_HREFLANG)),
        r("hreflang_missing_return", "Missing Return Links", "issue", "high",
          "Альтернативная страница не ссылается hreflang-ом обратно: поисковик может проигнорировать пару.",
          _hreflang_by_page("missing_return", "t.url"), (STORE_HREFLANG, FOLLOW_HREFLANG)),
        r("hreflang_inconsistent", "Inconsistent Language & Region Return Links", "issue", "high",
          "Обратная ссылка указывает для страницы другой язык/регион, чем страница указывает сама себе.",
          _hreflang_by_page("inconsistent", "s.url || ': ' || l.hreflang", report_target=True)),
        r("hreflang_non_canonical_return", "Non-Canonical Return Links", "issue", "high",
          "Hreflang ведёт на неканонический URL (у цели canonical на другой адрес).",
          _hreflang_by_page("non_canonical", "t.url || ' → ' || p.canonical_url"), (STORE_HREFLANG, FOLLOW_HREFLANG)),
        r("hreflang_noindex_return", "Noindex Return Links", "issue", "high",
          "Hreflang ведёт на страницу с noindex: в выдаче её не будет, пара языков разорвана.",
          _hreflang_by_page("noindex_return", "t.url"), (STORE_HREFLANG, FOLLOW_HREFLANG)),
        r("hreflang_incorrect_codes", "Incorrect Language & Region Codes", "issue", "high",
          "Код не по ISO 639-1 (язык) и ISO 3166-1 alpha-2 (регион): например, en-UK вместо en-GB.",
          _hreflang_codes),
        r("hreflang_multiple_entries", "Multiple Entries", "issue", "high",
          "Один и тот же язык/регион указан для разных URL.",
          _links_sql("SELECT s.url, group_concat(g.code, ', ') FROM (SELECT source_id, lower(hreflang) AS code"
                     " FROM link_rows WHERE crawl_id = :crawl_id AND kind = 'hreflang' GROUP BY source_id,"
                     " lower(hreflang) HAVING count(DISTINCT target_id) > 1) g JOIN urls s ON s.id = g.source_id"
                     " GROUP BY s.url ORDER BY s.url")),
        r("hreflang_not_using_canonical", "Not Using Canonical", "issue", "high",
          "У страницы canonical на другой URL, а её hreflang-разметка не указывает этот canonical.",
          _hreflang_pages(f"p.canonical_url IS NOT NULL AND p.canonical_url <> p.url"
                          f" AND NOT {_annotates(_CANONICAL_ID)}", "p.canonical_url")),
        r("hreflang_outside_head", "Outside <head>", "issue", "high",
          "<link rel=\"alternate\" hreflang> вне <head>: поисковик его проигнорирует.",
          _sql("hreflang_outside_head > 0", "CAST(hreflang_outside_head AS TEXT)"), ()),
        r("hreflang_unlinked", "Unlinked Hreflang URLs", "issue", "medium",
          "URL найден только через hreflang: обычные ссылки на него не ведут.",
          _links_sql("SELECT u.url, NULL FROM (SELECT DISTINCT target_id FROM link_rows WHERE crawl_id = :crawl_id"
                     " AND kind = 'hreflang') h JOIN urls u ON u.id = h.target_id"
                     " JOIN pages t ON t.crawl_id = :crawl_id AND t.url = u.url AND NOT coalesce(t.external, FALSE)"
                     " WHERE NOT EXISTS (SELECT 1 FROM link_rows l WHERE l.crawl_id = :crawl_id"
                     " AND l.target_id = h.target_id AND l.kind = 'hyperlink') ORDER BY u.url"),
          (STORE_HREFLANG, STORE_INTERNAL)),
        r("hreflang_missing_self_reference", "Missing Self Reference", "warning", "low",
          "В hreflang-разметке страницы нет её самой (ни её URL, ни её canonical).",
          _hreflang_pages(f"NOT {_annotates('h.source_id')} AND NOT {_annotates(_CANONICAL_ID)}")),
        r("hreflang_missing_x_default", "Missing X-Default", "warning", "low",
          "Нет x-default — версии для остальных языков (необязательно, но рекомендуется).",
          _hreflang_pages("NOT EXISTS (SELECT 1 FROM link_rows a WHERE a.crawl_id = :crawl_id AND a.kind = 'hreflang'"
                          " AND a.source_id = h.source_id AND lower(a.hreflang) = 'x-default')")),
    ]  # fmt: skip


# --- Pagination: rel next / prev link rows (kinds "next" / "prev") and pages.pagination.
STORE_PAGINATION = "collect.pagination.store"
FOLLOW_PAGINATION = "collect.pagination.follow"


def _pagination_by(filter_name: str, detail: str, report_target: bool = False) -> RuleFinder:
    """rel next / prev links passing one of the report's filters, one finding per page."""
    page = "t.url" if report_target else "s.url"
    return _links_sql(
        f"SELECT {page}, group_concat({detail}, '; ') FROM link_rows l"  # noqa: S608 — fixed rule text
        " JOIN urls s ON s.id = l.source_id JOIN urls t ON t.id = l.target_id"
        " LEFT JOIN pages p ON p.crawl_id = l.crawl_id AND p.url = t.url"
        f" WHERE l.crawl_id = :crawl_id AND l.kind IN ('next', 'prev') AND ({pagination_module.FILTERS[filter_name]})"
        f" GROUP BY {page} ORDER BY {page}"
    )


def _pagination_loops(conn: sa.Connection, crawl_id: int, _thresholds: ThresholdSettings) -> Iterable[Finding]:
    found: dict[str, str] = {}
    for url, detail in pagination_module.looping(conn, crawl_id):
        found.setdefault(url, detail)  # a page on both a next and a prev loop: reported once
    return sorted(found.items())


def _pagination_rules() -> list[Rule]:
    def r(code, name, kind, priority, description, find, requires=(STORE_PAGINATION,)) -> Rule:
        return Rule(code, "Pagination", f"Pagination: {name}", kind, priority, description, find, requires)

    return [
        r("pagination_not_in_anchor", "Pagination URL Not In Anchor Tag", "issue", "high",
          "URL из rel=next / prev не стоит обычной ссылкой <a> на самой странице: поисковик может не пойти по нему.",
          _pagination_by("not_in_anchor", "l.kind || ' ' || t.url"), (STORE_PAGINATION, STORE_INTERNAL)),
        r("pagination_non_200", "Non-200 Pagination URLs", "issue", "high",
          "URL из rel=next / prev отвечает не 200: редирект, ошибка, запрет robots.txt.",
          _pagination_by("non_200", "l.kind || ' ' || t.url || ' — ' || coalesce(p.blocked, CAST(p.status_code AS TEXT))"),
          (STORE_PAGINATION, FOLLOW_PAGINATION)),
        r("pagination_unlinked", "Unlinked Pagination URLs", "issue", "medium",
          "На URL из rel=next / prev нет обычных ссылок по сайту: страница находится только через пагинацию.",
          _pagination_by("unlinked", "s.url", report_target=True), (STORE_PAGINATION, STORE_INTERNAL)),
        r("pagination_multiple", "Multiple Pagination URLs", "issue", "low",
          "Несколько разных rel=next или rel=prev на странице: поисковик не поймёт, какая следующая.",
          _links_sql("SELECT s.url, group_concat(g.kind || ' ×' || g.n, ', ') FROM (SELECT source_id, kind,"
                     " count(DISTINCT target_id) AS n FROM link_rows l WHERE crawl_id = :crawl_id"
                     " AND l.kind IN ('next', 'prev') GROUP BY source_id, kind HAVING count(DISTINCT target_id) > 1) g"
                     " JOIN urls s ON s.id = g.source_id GROUP BY s.url ORDER BY s.url")),
        r("pagination_loop", "Pagination Loop", "issue", "low",
          "Цепочка rel=next (или rel=prev) возвращается на уже пройденную страницу.", _pagination_loops),
        r("pagination_sequence_error", "Sequence Error", "issue", "low",
          "Пары next / prev не сходятся: страница A ведёт next на B, а B не ведёт prev на A (или наоборот).",
          _pagination_by("sequence_error", "l.kind || ' ' || t.url"), (STORE_PAGINATION, FOLLOW_PAGINATION)),
        r("pagination_non_indexable", "Non-Indexable", "warning", "high",
          "Страница серии пагинации неиндексируемая (часто canonical страниц 2+ на первую): товары с этих "
          "страниц поисковик может не найти.", _sql("pagination IS NOT NULL AND NOT indexable", "indexability_status"),
          ()),
    ]  # fmt: skip


# --- Security: headers and page facts are columns written by the crawl; mixed content and forms are link rows.
def _https_to_http(kinds: str) -> RuleFinder:
    """HTTPS pages pointing at HTTP URLs through links of these kinds, one finding per page."""
    return _links_sql(
        f"SELECT source, group_concat(kind || ' ' || target, '; ') FROM ({security_module.insecure_links(kinds)})"  # noqa: S608
        " GROUP BY source ORDER BY source"
    )


def _security_rules() -> list[Rule]:
    def r(code, name, kind, priority, description, find, requires=()) -> Rule:
        return Rule(code, "Security", f"Security: {name}", kind, priority, description, find, requires)

    def header(code, name, flag, description, where=HTML_OK) -> Rule:
        return r(code, name, "warning", "low", description, _sql(f"{where} AND security_missing LIKE '%,{flag},%'"))

    return [
        r("security_http_urls", "HTTP URLs", "issue", "high",
          "URL сайта по незащищённому HTTP: данные между браузером и сайтом не шифруются.",
          _sql("url LIKE 'http://%'")),
        r("security_mixed_content", "Mixed Content", "issue", "high",
          "HTTPS-страница грузит картинки, CSS, JS или фреймы по HTTP: браузер их блокирует или предупреждает.",
          _https_to_http(security_module.RESOURCES), ("collect.images.store",)),
        r("security_form_url_insecure", "Form URL Insecure", "issue", "high",
          "На HTTPS-странице форма отправляется на HTTP-адрес: введённые данные уйдут незашифрованными.",
          _https_to_http("('form')"), (STORE_INTERNAL,)),
        r("security_form_on_http", "Form On HTTP URL", "issue", "high",
          "Форма на HTTP-странице: логины, пароли и прочие данные передаются незашифрованными.",
          _sql(f"{HTML_OK} AND forms > 0 AND url LIKE 'http://%'", "forms || ' форм'")),
        header("security_missing_hsts", "Missing HSTS Header", "hsts",
               "Нет Strict-Transport-Security: браузер не обязан открывать сайт только по HTTPS.",
               f"{HTML_OK} AND url LIKE 'https://%'"),
        r("security_unsafe_cross_origin", "Unsafe Cross Origin Links", "warning", "low",
          "Ссылки target=\"_blank\" на чужие сайты без rel=\"noopener\" / \"noreferrer\": открытая вкладка "
          "получает доступ к window.opener.",
          _sql(f"{HTML_OK} AND unsafe_blank_links > 0", "unsafe_blank_links || ' шт.'")),
        r("security_protocol_relative", "Protocol-Relative Resource Links", "warning", "low",
          "Ресурсы подключены как //host/…: на HTTP-странице они тоже грузятся по HTTP. Лучше явный https://.",
          _sql(f"{HTML_OK} AND protocol_relative > 0", "protocol_relative || ' шт.'")),
        header("security_missing_csp", "Missing Content-Security-Policy Header", "csp",
               "Нет Content-Security-Policy: браузер не ограничивает, откуда странице грузить скрипты и ресурсы."),
        header("security_missing_x_content_type_options", "Missing X-Content-Type-Options Header", "xcto",
               "Нет X-Content-Type-Options: nosniff — браузер может «угадывать» тип файла вопреки заголовку."),
        header("security_missing_x_frame_options", "Missing X-Frame-Options Header", "xfo",
               "Нет X-Frame-Options: DENY или SAMEORIGIN — страницу можно встроить в чужой фрейм (кликджекинг)."),
        header("security_missing_referrer_policy", "Missing Secure Referrer-Policy Header", "referrer",
               "Referrer-Policy нет или он небезопасный (не no-referrer, no-referrer-when-downgrade, strict-origin, "
               "strict-origin-when-cross-origin): адрес страницы уходит чужим сайтам целиком."),
        r("security_bad_content_type", "Bad Content Type", "warning", "low",
          "Содержимое не совпадает с заголовком Content-Type (например, HTML под image/png): браузер и поисковик "
          "могут обработать его неверно.", _sql("sniffed_type IS NOT NULL", "sniffed_type")),
    ]  # fmt: skip


def _structured_rules() -> list[Rule]:
    def r(code, name, kind, priority, description, column) -> Rule:
        return Rule(code, "Structured Data", f"Structured Data: {name}", kind, priority, description,
                    _sql(f"{HTML_OK} AND {column} > 0", f"{column} || ' шт., типы ' || coalesce(sd_types, '—')"),
                    ("collect.structured_data",))  # fmt: skip

    return [
        r("structured_data_validation_errors", "Validation Errors", "issue", "high",
          "Ошибки по словарю Schema.org: несуществующий тип или свойство, свойство не того типа. Список — "
          "`spider url` и `spider structured`.", "sd_errors"),
        r("structured_data_rich_result_errors", "Rich Result Validation Errors", "issue", "high",
          "Для расширенного результата Google не хватает обязательных свойств (Product, Recipe, Event…).",
          "sd_rich_errors"),
        r("structured_data_parse_errors", "Parse Errors", "issue", "high",
          "Микроразметка не разбирается: битый JSON-LD, ошибка Microdata / RDFa.", "sd_parse_errors"),
        Rule("structured_data_missing", "Structured Data", "Structured Data: Missing", "opportunity", "low",
             "На странице нет микроразметки выбранных форматов (collect.structured_data).",
             _sql(f"{HTML_OK} AND sd_formats = ''"), ("collect.structured_data",)),
        r("structured_data_validation_warnings", "Validation Warnings", "opportunity", "low",
          "Предупреждения Schema.org: устаревший data-vocabulary.org, устаревшие (superseded) типы и свойства.",
          "sd_warnings"),
        r("structured_data_rich_result_warnings", "Rich Result Validation Warnings", "opportunity", "low",
          "Для расширенного результата Google нет рекомендуемых свойств.", "sd_rich_warnings"),
    ]  # fmt: skip


def _sitemap_rules() -> list[Rule]:
    def r(code, name, kind, priority, description, query, requires=("sitemaps.crawl",)) -> Rule:
        return Rule(code, "Sitemaps", f"Sitemaps: {name}", kind, priority, description, _links_sql(query), requires)

    by_file = "SELECT url, {detail} FROM sitemap_files WHERE crawl_id = :crawl_id AND {where} ORDER BY url"
    return [
        r("sitemaps_over_max_urls", "XML Sitemap With Over 50k URLs", "issue", "high",
          "В одном файле sitemap больше thresholds.sitemap_max_urls (50 000) URL: поисковик прочитает не всё.",
          by_file.format(detail="urls || ' URL'", where="urls > :sitemap_max_urls")),
        r("sitemaps_over_max_mb", "XML Sitemap Over 50mb", "issue", "high",
          "Файл sitemap больше thresholds.sitemap_max_mb (50) МБ без сжатия: поисковик его не дочитает.",
          by_file.format(detail="round(bytes / 1048576.0, 1) || ' МБ'", where="bytes > :sitemap_max_mb * 1048576")),
        r("sitemaps_urls_not_in_sitemap", "URLs Not In Sitemap", "issue", "medium",
          "Индексируемая страница сайта не указана ни в одном sitemap.",
          f"SELECT url, NULL FROM ({sitemaps_module.QUERIES['not_in_sitemap']}) ORDER BY url"),  # noqa: S608
        r("sitemaps_orphan_urls", "Orphan URLs", "issue", "medium",
          "URL есть в sitemap, но обычных ссылок на него на сайте нет («сирота»): поисковик найдёт его только "
          "через sitemap.", f"SELECT url, source FROM ({sitemaps_module.QUERIES['orphans']}) ORDER BY url",  # noqa: S608
          ("sitemaps.crawl", STORE_INTERNAL)),
        r("sitemaps_non_indexable", "Non-Indexable URLs In Sitemap", "issue", "medium",
          "В sitemap неиндексируемый URL (редирект, ошибка, noindex, canonical на другой): sitemap должен "
          "перечислять только то, что стоит индексировать.",
          "SELECT s.url, min(p.indexability_status) FROM sitemap_urls s JOIN pages p ON p.crawl_id = s.crawl_id"
          " AND p.url = s.url WHERE s.crawl_id = :crawl_id AND NOT coalesce(p.external, FALSE) AND NOT p.indexable"
          " GROUP BY s.url ORDER BY s.url"),
        r("sitemaps_multiple", "URLs In Multiple Sitemaps", "warning", "low",
          "URL указан в нескольких файлах sitemap.",
          "SELECT url, count(DISTINCT source) || ' файл(ов)' FROM sitemap_urls WHERE crawl_id = :crawl_id"
          " GROUP BY url HAVING count(DISTINCT source) > 1 ORDER BY url"),
    ]  # fmt: skip


def _javascript_rules() -> list[Rule]:
    """Raw vs rendered HTML: what JavaScript changes on a page (crawl.render), and the old AJAX crawling scheme."""

    def js(code, name, kind, priority, description, where, detail="NULL", requires=(RENDERED,)) -> Rule:
        return Rule(code, "JavaScript", f"JavaScript: {name}", kind, priority, description,
                    _sql(f"{HTML_OK} AND {'rendered AND ' if RENDERED in requires else ''}({where})", detail),
                    requires)  # fmt: skip

    def only_rendered(raw: str, now: str) -> str:
        return f"trim(coalesce({raw}, '')) = '' AND trim(coalesce({now}, '')) <> ''"

    def updated(raw: str, now: str) -> str:
        return f"trim(coalesce({raw}, '')) <> '' AND trim(coalesce({now}, '')) <> '' AND {raw} <> {now}"

    def changed(raw: str, now: str) -> str:
        return f"{raw} || ' → ' || {now}"

    return [
        js("js_noindex_only_original", "Noindex Only in Original HTML", "issue", "high",
           "noindex есть в HTML ответа сервера, но скрипт его убирает: Google может увидеть noindex до рендеринга "
           "и не отрендерить страницу вовсе — она выпадет из индекса.",
           "raw_directives LIKE '%,noindex,%' AND coalesce(robots_directives, '') NOT LIKE '%,noindex,%'"),
        js("js_nofollow_only_original", "Nofollow Only in Original HTML", "issue", "high",
           "nofollow есть в HTML ответа сервера, но скрипт его убирает: поисковик может не пойти по ссылкам.",
           "raw_directives LIKE '%,nofollow,%' AND coalesce(robots_directives, '') NOT LIKE '%,nofollow,%'"),
        js("js_canonical_mismatch", "Canonical Mismatch", "issue", "high",
           "canonical в HTML ответа сервера и после выполнения JS разный: поисковик получает два разных сигнала.",
           "raw_canonical IS NOT NULL AND canonical_url IS NOT NULL AND raw_canonical <> canonical_url",
           changed("raw_canonical", "canonical_url")),
        js("js_ajax_scheme_urls", "Uses Old AJAX Crawling Scheme URLs", "issue", "medium",
           "Ссылки вида #! или URL с _escaped_fragment_ — схема AJAX-обхода, которую Google отменил в 2015: "
           "такие адреса больше не индексируются как отдельные страницы.",
           "hashbang_links > 0 OR instr(url, '_escaped_fragment_=') > 0",
           "CASE WHEN hashbang_links > 0 THEN hashbang_links || ' ссылок с #!' ELSE '_escaped_fragment_' END", ()),
        js("js_ajax_meta_fragment", "Uses Old AJAX Crawling Scheme Meta Fragment Tag", "issue", "medium",
           "На странице <meta name=\"fragment\" content=\"!\"> отменённой в 2015 схемы AJAX-обхода: тег "
           "ничего не даёт, контент нужно отдавать обычным HTML или рендерингом.", "ajax_meta_fragment", requires=()),
        js("js_blocked_resources", "Pages with Blocked Resources", "warning", "high",
           "robots.txt закрывает скрипты, стили или картинки страницы: поисковик отрендерит её без них и может "
           "увидеть не то, что пользователь. Какие — `spider report javascript --only resources`.",
           "blocked_resources > 0", "blocked_resources || ' шт.'", (RENDERED, "crawl.robots=respect")),
        js("js_links", "Contains JavaScript Links", "warning", "medium",
           "Ссылки, которых нет в HTML ответа сервера, их добавляет JS: поисковик увидит их только после "
           "рендеринга, позже и не всегда. Какие — `spider links <url>`, колонка origin.",
           "js_outlinks > 0", "js_outlinks || ' шт.'"),
        js("js_content", "Contains JavaScript Content", "warning", "medium",
           "Текст, которого нет в HTML ответа сервера: хотя бы thresholds.js_content_min_words (10) слов добавляет JS.",
           "coalesce(word_count, 0) - coalesce(raw_word_count, 0) >= :js_content_min_words",
           "coalesce(raw_word_count, 0) || ' → ' || coalesce(word_count, 0) || ' слов'"),
        js("js_title_only_rendered", "Page Title Only in Rendered HTML", "warning", "medium",
           "title нет в HTML ответа сервера, его ставит JS.", only_rendered("raw_title", "title"), "title"),
        js("js_title_updated", "Page Title Updated by JavaScript", "warning", "medium",
           "JS меняет title: поисковик может показать исходный.", updated("raw_title", "title"),
           changed("raw_title", "title")),
        js("js_description_only_rendered", "Meta Description Only in Rendered HTML", "warning", "medium",
           "meta description нет в HTML ответа сервера, его ставит JS.",
           only_rendered("raw_meta_description", "meta_description"), "meta_description"),
        js("js_description_updated", "Meta Description Updated by JavaScript", "warning", "medium",
           "JS меняет meta description.", updated("raw_meta_description", "meta_description"),
           changed("raw_meta_description", "meta_description")),
        js("js_h1_only_rendered", "H1 Only in Rendered HTML", "warning", "medium",
           "H1 нет в HTML ответа сервера, его добавляет JS.", only_rendered("raw_h1", "h1"), "h1"),
        js("js_h1_updated", "H1 Updated by JavaScript", "warning", "medium",
           "JS меняет H1.", updated("raw_h1", "h1"), changed("raw_h1", "h1")),
        js("js_canonical_only_rendered", "Canonical Only in Rendered HTML", "warning", "low",
           "canonical нет в HTML ответа сервера, его добавляет JS: Google советует canonical в исходном HTML.",
           "raw_canonical IS NULL AND canonical_url IS NOT NULL", "canonical_url"),
        js("js_errors", "Pages With JavaScript Errors", "warning", "low",
           "Ошибки в консоли браузера при рендеринге: сломанный скрипт может не показать контент или ссылки. "
           "Тексты — `spider report javascript`.",
           "js_errors > 0", "js_errors || ' ошибок'", (RENDERED, "crawl.render_console")),
    ]  # fmt: skip


# Screaming Frog's PageSpeed opportunities by the Lighthouse (13) audit that answers each: failed = score under 0.9.
PAGESPEED = (
    ("document-latency-insight", "Document Request Latency", "medium",
     "Основной документ отдаётся медленно: редиректы, долгий ответ сервера или нет сжатия."),
    ("lcp-discovery-insight", "LCP Request Discovery", "medium",
     "Ресурс крупнейшего элемента экрана (LCP) браузер находит поздно: нет fetchpriority=high / preload, lazy-load."),
    ("render-blocking-insight", "Render Blocking Requests", "medium",
     "Скрипты и стили блокируют первую отрисовку: нет defer / async, стили не разделены по media."),
    ("network-dependency-tree-insight", "Network Dependency Tree", "medium",
     "Длинные цепочки загрузки на критическом пути: ресурсы грузятся друг за другом."),
    ("cache-insight", "Use Efficient Cache Lifetimes", "medium",
     "Статические ресурсы без нормального HTTP-кэширования: при повторном заходе качаются снова."),
    ("cls-culprits-insight", "Layout Shift Culprits", "medium",
     "Элементы сдвигают вёрстку при загрузке (CLS): картинки без размеров, вставки, шрифты."),
    ("image-delivery-insight", "Improve Image Delivery", "medium",
     "Картинки можно отдавать легче: современный формат, нужный размер, сжатие."),
    ("forced-reflow-insight", "Forced Reflow", "medium",
     "Скрипт читает геометрию DOM сразу после изменения — принудительный пересчёт раскладки."),
    ("legacy-javascript-insight", "Legacy JavaScript", "medium",
     "Полифиллы и преобразования для старых браузеров, которые современным не нужны."),
    ("duplicated-javascript-insight", "Duplicated JavaScript", "medium",
     "Одна и та же JS-библиотека в нескольких бандлах."),
    ("total-byte-weight", "Avoid Enormous Network Payloads", "medium",
     "Страница весит слишком много (медиана по HTTP Archive — 1,7–1,9 МБ)."),
    ("unminified-css", "Minify CSS", "medium", "CSS не минифицирован."),
    ("unminified-javascript", "Minify JavaScript", "medium", "JavaScript не минифицирован."),
    ("unused-css-rules", "Reduce Unused CSS", "medium", "Много CSS, который страница не использует."),
    ("unused-javascript", "Reduce Unused JavaScript", "medium", "Много JavaScript, который страница не выполняет."),
    ("bootup-time", "Reduce JavaScript Execution Time", "medium", "Выполнение JavaScript занимает больше 2 секунд."),
    ("mainthread-work-breakdown", "Minimize Main-Thread Work", "medium",
     "Главный поток браузера занят дольше 4 секунд при загрузке."),
    ("dom-size-insight", "Optimize DOM Size", "low", "Большой DOM: пересчёт стилей и раскладки дольше 40 мс."),
    ("font-display-insight", "Font Display", "low", "Шрифты «мигают» или невидимы при загрузке (нет font-display)."),
)  # fmt: skip
_AUDIT_FINDINGS = (
    "SELECT url, min(coalesce(display, '')) FROM lighthouse_audits WHERE crawl_id = :crawl_id AND audit = '{audit}'"
    " AND score < 0.9 GROUP BY url ORDER BY url"
)


def _lighthouse_rules() -> list[Rule]:
    """PageSpeed and the Mobile audits of `spider lighthouse` (not checked until it has run for the crawl)."""
    how = " Данные — `spider lighthouse` (выборка типовых страниц); детали — `spider lighthouse --show`."

    def audit(audit_id: str) -> RuleFinder:
        return _run_sql(sa.text(_AUDIT_FINDINGS.format(audit=audit_id)))

    rules = [Rule(f"pagespeed_{audit_id.removesuffix('-insight').replace('-', '_')}", "PageSpeed", f"PageSpeed: {name}",
                  "opportunity", priority, description + how, audit(audit_id), ("data:lighthouse",))
             for audit_id, name, priority, description in PAGESPEED]  # fmt: skip
    rules += [
        Rule("mobile_content_not_sized", "Mobile", "Mobile: Content Not Sized Correctly", "issue", "high",
             "Контент шире экрана телефона: появляется горизонтальная прокрутка." + how,
             audit("spider-content-width"), ("data:mobile-measures",)),
        Rule("mobile_illegible_font_size", "Mobile", "Mobile: Illegible Font Size", "issue", "high",
             "Больше 40 % текста мельче 12 px: на телефоне его трудно читать." + how,
             audit("spider-font-size"), ("data:mobile-measures",)),
        Rule("mobile_target_size", "Mobile", "Mobile: Target Size", "issue", "medium",
             "Ссылки и кнопки слишком маленькие или стоят слишком тесно для пальца." + how,
             audit("target-size"), ("data:lighthouse",)),
    ]  # fmt: skip
    return rules


LIGHTHOUSE_CODES = {r.code for r in _lighthouse_rules()}
# the Lighthouse audits (and spider's own mobile measures) the rules above judge
CHECKED_AUDITS = (*(a[0] for a in PAGESPEED), "target-size", "spider-content-width", "spider-font-size")


def refresh(engine: sa.Engine, crawl_id: int, codes: set[str], thresholds: ThresholdSettings | None = None) -> int:
    """Recompute some rules only (their findings replaced) — after data collected on request, without a full
    `analyze`. Returns their number of findings."""
    thresholds = thresholds or ThresholdSettings()
    skipped = {r.code for r in not_checked(engine, crawl_id)}
    found = 0
    with engine.begin() as conn:
        conn.execute(sa.delete(storage.issues).where(storage.issues.c.crawl_id == crawl_id,
                                                     storage.issues.c.code.in_(codes)))  # fmt: skip
        for r in RULES:
            if r.code in codes and r.code not in skipped and isinstance(r.find, SqlFinder):
                found += r.find.store(conn, crawl_id, r.code, thresholds)
    return found


def _validation_mobile_rules() -> list[Rule]:
    def v(code, name, kind, description, where, detail="NULL", requires=("collect.html_validation",)) -> Rule:
        return Rule(code, "Validation", f"Validation: {name}", kind, "high", description,
                    _sql(f"{HTML_OK} AND {where}", detail), requires)  # fmt: skip

    def m(code, name, kind, description, find, requires=()) -> Rule:
        return Rule(code, "Mobile", f"Mobile: {name}", kind, "high", description, find, requires)

    size = "round(bytes / 1048576.0, 1) || ' МБ'"
    return [
        v("validation_missing_head", "Missing <head> Tag", "issue",
          "В исходном HTML нет <head>: браузер его достроит, но разметка ненадёжна для поисковика.", "head_tags = 0"),
        v("validation_multiple_head", "Multiple <head> Tags", "issue",
          "Несколько <head>: второй поисковик может не прочитать.", "head_tags > 1", "CAST(head_tags AS TEXT)"),
        v("validation_missing_body", "Missing <body> Tag", "issue", "В исходном HTML нет <body>.", "body_tags = 0"),
        v("validation_multiple_body", "Multiple <body> Tags", "issue",
          "Несколько <body>.", "body_tags > 1", "CAST(body_tags AS TEXT)"),
        v("validation_document_over_max", "HTML Document Over 2MB", "issue",
          "HTML больше thresholds.document_max_mb (2) МБ: Googlebot читает только первые 2 МБ.",
          "bytes > :document_max_mb * 1048576", size, ()),
        Rule("validation_resource_over_max", "Validation", "Validation: Resource Over 2MB", "issue", "high",
             "JS / CSS больше thresholds.resource_max_mb (2) МБ: Googlebot читает только первые 2 МБ файла.",
             _sql("status_code = 200 AND (content_type LIKE '%javascript%' OR content_type LIKE '%ecmascript%'"
                  " OR content_type LIKE '%css%') AND bytes > :resource_max_mb * 1048576", size)),
        v("validation_invalid_head_elements", "Invalid HTML Elements In <head>", "warning",
          "В <head> элемент, которому там не место (div, img, iframe…): Google считает <head> законченным и "
          "не видит title, meta и canonical после него.", "invalid_head_element IS NOT NULL", "invalid_head_element"),
        v("validation_body_before_html", "<body> Element Preceding <html>", "warning",
          "Элементы страницы стоят раньше <html>.", "body_before_html"),
        v("validation_head_not_first", "<head> Not First In <html> Element", "warning",
          "Внутри <html> первым идёт не <head>.", "head_not_first"),
        # plugins IS NOT NULL: the page was read by a spider that looks for the viewport (older crawls: not checked)
        m("mobile_viewport_not_set", "Viewport Not Set", "issue",
          "Нет <meta name=\"viewport\"> с width=: на телефоне страница откроется в ширину десктопа.",
          _sql(f"{HTML_OK} AND plugins IS NOT NULL AND coalesce(viewport, '') NOT LIKE '%width=%'", "viewport")),
        m("mobile_unsupported_plugins", "Contains Unsupported Plugins", "issue",
          "Flash, Silverlight или Java-апплет (<object>, <embed>, <applet>): телефоны их не показывают, поисковики "
          "не индексируют.", _sql(f"{HTML_OK} AND plugins > 0", "plugins || ' шт.'")),
        m("mobile_alternate_link", "Mobile Alternate Link", "warning",
          "Отдельная мобильная версия (<link rel=\"alternate\" media=…>): Google рекомендует адаптивный дизайн на "
          "одном URL; убедитесь, что версии связаны в обе стороны.",
          _links_sql("SELECT s.url, min(t.url) FROM link_rows l JOIN urls s ON s.id = l.source_id"
                     " JOIN urls t ON t.id = l.target_id WHERE l.crawl_id = :crawl_id AND l.kind = 'mobile_alternate'"
                     " GROUP BY s.url ORDER BY s.url"), ("collect.mobile_alternate.store",)),
    ]  # fmt: skip


RESOURCE_KINDS = "('image', 'css', 'js', 'media', 'iframe')"


def _image_rules() -> list[Rule]:
    def img(code, name, kind, priority, description, where, detail="''", requires=("collect.images.store",)) -> Rule:
        """A rule over the page's <img> link rows; reported by image URL, detail — where it's used."""
        query = (  # grouped over URL ids; the example page's URL is looked up once per image
            f"SELECT u.url, g.n || ' стр., например ' || e.url || g.extra FROM (SELECT target_id,"  # noqa: S608 — fixed rule text
            f" count(DISTINCT source_id) AS n, min(source_id) AS example, {detail} AS extra FROM link_rows"
            f" WHERE crawl_id = :crawl_id AND kind = 'image' AND ({where}) GROUP BY target_id) AS g"
            " JOIN urls u ON u.id = g.target_id JOIN urls e ON e.id = g.example ORDER BY u.url"
        )
        return Rule(code, "Images", f"Images: {name}", kind, priority, description, _links_sql(query), requires)

    def blocked(code, name, priority, external) -> Rule:
        where = "coalesce(p.external, FALSE)" if external else "NOT coalesce(p.external, FALSE)"
        return Rule(code, "Response Codes", name, "warning", priority,
                    ("Внешний" if external else "Внутренний") + " ресурс (картинка, CSS, JS…) недоступен: "
                    "запрещён robots.txt, не отвечает или отдаёт ошибку — страница может отображаться неполно.",
                    _links_sql(
                        "SELECT p.url, coalesce(p.blocked, CAST(p.status_code AS TEXT)) FROM pages p"  # noqa: S608
                        f" WHERE p.crawl_id = :crawl_id AND {where}"
                        " AND (p.blocked IS NOT NULL OR p.status_code = 0 OR p.status_code >= 400)"
                        " AND EXISTS (SELECT 1 FROM links l WHERE l.crawl_id = p.crawl_id AND l.target = p.url"
                        f"   AND l.kind IN {RESOURCE_KINDS}) ORDER BY p.url"
                    ),
                    ("collect.images.follow",))  # fmt: skip

    return [
        img("images_missing_alt_text", "Missing Alt Text", "issue", "low",
            "Атрибут alt есть, но пустой: для поисковика и незрячих картинка без описания "
            "(нормально только для декоративных).", "alt_attr AND trim(coalesce(alt, '')) = ''"),
        img("images_missing_alt_attribute", "Missing Alt Attribute", "issue", "low",
            "У <img> нет атрибута alt вовсе.", "NOT alt_attr"),
        Rule("images_over_max_kb", "Images", "Images: Over Max KB", "opportunity", "medium",
             "Картинка тяжелее thresholds.image_kb КБ: замедляет загрузку страницы.",
             _links_sql(
                 "SELECT p.url, (p.bytes / 1024) || ' КБ' FROM pages p WHERE p.crawl_id = :crawl_id"
                 " AND p.bytes > :image_kb * 1024 AND EXISTS (SELECT 1 FROM links l WHERE l.crawl_id = p.crawl_id"
                 "   AND l.target = p.url AND l.kind = 'image') ORDER BY p.url"),
             ("collect.images.follow", "collect.images.store")),
        img("images_alt_over_max", "Alt Text Over Max Characters", "opportunity", "low",
            "Alt длиннее thresholds.alt_max_chars: описание должно быть коротким.",
            "length(alt) > :alt_max_chars", "' — ' || max(length(alt)) || ' симв.'"),
        img("images_missing_size", "Missing Size Attributes", "opportunity", "low",
            "У <img> не заданы width и height: страница «прыгает» при загрузке (CLS).", "NOT sized"),
        img("images_background", "Background Images", "warning", "low",
            "Картинка задана CSS-фоном (background-image), а не <img>: у неё нет alt, и поисковик в картинках её "
            "обычно не индексирует. Фоны из стилей видны только с рендерингом, из атрибута style — всегда.",
            "origin = 'c'"),
        Rule("images_incorrectly_sized", "Images", "Images: Incorrectly Sized Images", "opportunity", "low",
             "Картинка больше, чем показана на странице, — шире или выше в thresholds.image_oversize_ratio (2) раза и "
             "больше: лишние байты; отдайте картинку нужного размера (srcset). Нужны рендеринг и crawl.render_images.",
             _run_sql(sa.text(
                 "SELECT image, min(real_width || '×' || real_height || ' → ' || display_width || '×' || display_height"
                 " || ', ' || url) FROM rendered_images WHERE crawl_id = :crawl_id AND display_width > 0"
                 " AND display_height > 0 AND (real_width > display_width * :image_oversize_ratio"
                 " OR real_height > display_height * :image_oversize_ratio) GROUP BY image ORDER BY image")),
             (RENDERED, "crawl.render_images")),
        blocked("internal_blocked_resource", "Internal Blocked Resource", "high", external=False),
        blocked("external_blocked_resource", "External Blocked Resource", "medium", external=True),
    ]  # fmt: skip


RULES += _onpage_rules()
RULES += _directive_canonical_rules()
RULES += _content_rules()
RULES += _link_rules()
RULES += _image_rules()
RULES += _url_rules()
RULES += _hreflang_rules()
RULES += _pagination_rules()
RULES += _security_rules()
RULES += _structured_rules()
RULES += _sitemap_rules()
RULES += _validation_mobile_rules()
RULES += _javascript_rules()
RULES += _lighthouse_rules()
BY_CODE = {rule.code: rule for rule in RULES}
_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def rule(code: str) -> Rule:
    if code not in BY_CODE:
        raise InvalidArguments(f"Unknown issue code '{code}'. Known codes: {', '.join(BY_CODE)}.")
    return BY_CODE[code]


def collected(engine: sa.Engine, crawl_id: int) -> dict[str, Any]:
    """What the crawl collected: its settings snapshot as flat keys (defaults for crawls without one)."""
    _, snapshot = storage.get_crawl(engine, crawl_id)
    try:
        crawl_settings = Settings.model_validate(snapshot or {})
    except ValidationError:  # a snapshot from an older spider: assume the defaults
        crawl_settings = Settings()
    flat = settings_module.flatten(crawl_settings.model_dump())
    # data collected on request after the crawl: `data:<what>` is true when the crawl has it
    with engine.connect() as conn:
        audits = conn.execute(
            sa.text("SELECT min(audit) FROM lighthouse_audits WHERE crawl_id = :c AND audit LIKE 'spider-%'"
                    " UNION ALL SELECT min(url) FROM lighthouse_audits WHERE crawl_id = :c"), {"c": crawl_id},
        ).scalars().all()  # fmt: skip
    flat["data:lighthouse"] = audits[1] is not None
    flat["data:mobile-measures"] = audits[0] is not None
    return flat


def _met(collected: dict[str, Any], requirement: str) -> bool:
    """`key` — on during the crawl; `key=value` / `key!=value` — the key had (not) that value."""
    if "!=" in requirement:
        key, value = requirement.split("!=", 1)
        return str(collected.get(key)) != value
    if "=" in requirement:
        key, value = requirement.split("=", 1)
        return str(collected.get(key)) == value
    return bool(collected.get(requirement))


def not_checked(engine: sa.Engine, crawl_id: int) -> list[Rule]:
    """Rules this crawl can't answer: the data they need wasn't collected (`collect.*` off)."""
    done = collected(engine, crawl_id)
    return [r for r in RULES if not all(_met(done, key) for key in r.requires)]


def analyze(engine: sa.Engine, crawl_id: int, thresholds: ThresholdSettings | None = None) -> int:
    """(Re)compute every rule for a crawl, replacing earlier findings. Returns the number of findings.

    Rules whose data wasn't collected are skipped — `not_checked` lists them, so a report never says
    "no problems" about something that wasn't looked at.
    """
    thresholds = thresholds or ThresholdSettings()
    skipped = {r.code for r in not_checked(engine, crawl_id)}
    with engine.begin() as conn:
        # Planner statistics: without them SQLite may scan all of a crawl's links for every page instead of
        # finding the URL's id first (minutes instead of seconds). Sampled, so quick however big the database.
        if storage.is_sqlite(conn):
            conn.exec_driver_sql("PRAGMA analysis_limit = 1000")
        conn.exec_driver_sql("ANALYZE")
        steps: list[tuple[str, Callable[[], object]]] = [
            ("indexability", lambda: compute_indexability(conn, crawl_id, thresholds)),
            ("link counts", lambda: compute_link_counts(conn, crawl_id)),
            ("url flags", lambda: compute_url_issues(conn, crawl_id, thresholds)),
            ("serp widths", lambda: serp_module.compute(conn, crawl_id, thresholds)),
            ("near duplicates", lambda: duplicates_module.compute_near(conn, crawl_id, thresholds)),
            ("clear", lambda: conn.execute(sa.delete(storage.issues).where(storage.issues.c.crawl_id == crawl_id))),
        ]
        for name, step in steps:
            _timed(name, step)
        found = 0
        for r in RULES:
            if r.code in skipped:
                continue
            finder, code = r.find, r.code
            if isinstance(finder, SqlFinder):
                found += _timed(code, lambda f=finder, c=code: f.store(conn, crawl_id, c, thresholds))
            else:
                found += _timed(
                    code, lambda f=finder, c=code: _store_findings(conn, crawl_id, c, f(conn, crawl_id, thresholds))
                )
    return found


def _timed(name: str, step: Callable[[], Any]) -> Any:
    """Run one step of `analyze`, logging how long it took (`spider --verbose`): a slow rule shows itself."""
    started = time.monotonic()
    result = step()
    log.debug("analyze: %s %.2f s", name, time.monotonic() - started)
    return result


def _store_findings(conn: sa.Connection, crawl_id: int, code: str, findings: Iterable[Finding]) -> int:
    """A Python rule's findings, inserted as they come, a batch at a time: a generator rule never holds them all."""
    stored, rows = 0, []
    for url, detail in findings:
        rows.append({"crawl_id": crawl_id, "code": code, "url": url, "detail": detail})
        if len(rows) >= _URL_BATCH:
            conn.execute(sa.insert(storage.issues), rows)
            stored, rows = stored + len(rows), []
    if rows:
        conn.execute(sa.insert(storage.issues), rows)
    return stored + len(rows)


@dataclass
class IssueSummary:
    code: str
    group: str
    name: str
    type: str
    priority: str
    description: str
    urls: int
    percent: float  # of the site's own URLs in the crawl


def summary(engine: sa.Engine, crawl_id: int) -> list[IssueSummary]:
    """Rules that found something, most urgent first (priority, then number of URLs)."""
    query = (
        sa.select(storage.issues.c.code, sa.func.count())
        .where(storage.issues.c.crawl_id == crawl_id)
        .group_by(storage.issues.c.code)
    )
    own = sa.select(sa.func.count()).where(
        storage.pages.c.crawl_id == crawl_id, sa.not_(sa.func.coalesce(storage.pages.c.external, False))
    )
    with engine.connect() as conn:
        counts = {code: n for code, n in conn.execute(query)}
        total = conn.execute(own).scalar_one() or 1
    found = [
        IssueSummary(
            r.code,
            r.group,
            r.name,
            r.type,
            r.priority,
            r.description,
            counts[r.code],
            round(100 * counts[r.code] / total, 1),
        )
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
