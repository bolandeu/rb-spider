"""Reports over a stored crawl (`spider report …`): canonicals, site structure, response times, crawl path, meta
keywords, forms, HTTP headers and cookies, the browser's console log. Each is SQL over the crawl's tables, or a stream of its pages with small
counters (distinct folders up to a depth, header names, cookie names) — never a list of the site's pages.
"""

from __future__ import annotations

import json
from collections import Counter
from urllib.parse import urlsplit

import sqlalchemy as sa

from . import storage
from .errors import InvalidArguments
from .export import cookies_of
from .issues import CHECKED_AUDITS

OWN = "NOT coalesce(p.external, FALSE)"
HTML_OK = f"{OWN} AND p.parsed AND p.status_code = 200 AND p.content_type LIKE '%html%'"


def _rows(engine: sa.Engine, query: str, params: dict, limit: int | None) -> tuple[int, list[dict]]:
    with engine.connect() as conn:
        total = conn.execute(sa.text(f"SELECT count(*) FROM ({query})"), params).scalar_one()  # noqa: S608
        found = conn.execute(
            sa.text(f"{query} LIMIT :limit"), params | {"limit": storage.NO_LIMIT if limit is None else limit}
        )
        return total, [dict(row) for row in found.mappings()]


# --- canonicals ------------------------------------------------------------------------------------

CANONICALS = {
    # every page with a canonical to another URL, and what that URL is
    "all": "",
    # the target canonicalises or redirects further: a chain, not one step
    "chains": " AND (t.canonical_url IS NOT NULL AND t.canonical_url <> t.url OR t.redirect_url IS NOT NULL"
    " OR t.refresh_url IS NOT NULL)",
    # the target can't be indexed: the canonical points nowhere useful
    "non_indexable": " AND t.url IS NOT NULL AND NOT t.indexable",
}


def canonicals(engine: sa.Engine, crawl_id: int, only: str, limit: int | None = None) -> tuple[int, list[dict]]:
    """Canonical Chains / Non-Indexable Canonicals: pages whose canonical names another URL, with that URL's state."""
    if only not in CANONICALS:
        raise InvalidArguments(f"--only: one of {', '.join(CANONICALS)}.")
    query = (
        "SELECT p.url, p.canonical_url AS canonical, t.status_code AS canonical_status,"  # noqa: S608 — fixed text
        " t.indexability_status AS canonical_indexability, coalesce(t.canonical_url, t.redirect_url, t.refresh_url)"
        " AS next_hop FROM spider_pages p LEFT JOIN spider_pages t ON t.crawl_id = p.crawl_id AND t.url = p.canonical_url"
        f" WHERE p.crawl_id = :crawl_id AND {OWN} AND p.canonical_url IS NOT NULL AND p.canonical_url <> p.url"
        f"{CANONICALS[only]} ORDER BY p.url"
    )
    return _rows(engine, query, {"crawl_id": crawl_id}, limit)


# --- site structure --------------------------------------------------------------------------------


def structure(engine: sa.Engine, crawl_id: int, depth: int = 2) -> dict:
    """Site Structure: folders down to `depth` levels with their URLs (indexable / not), and URLs per crawl depth.

    Streams the site's URLs once; the counters hold one entry per folder at most `depth` levels deep.
    """
    folders: Counter[str] = Counter()
    indexable: Counter[str] = Counter()
    query = sa.text(f"SELECT p.url, p.indexable FROM spider_pages p WHERE p.crawl_id = :crawl_id AND {OWN}")  # noqa: S608
    with engine.connect() as conn:
        for url, is_indexable in storage.streamed(conn, 2000).execute(query, {"crawl_id": crawl_id}):
            segments = [s for s in urlsplit(url).path.split("/")[1:-1] if s][:depth]  # folders, not the page
            folder = "/" + "".join(f"{s}/" for s in segments)
            folders[folder] += 1
            indexable[folder] += bool(is_indexable)
        depths = conn.execute(
            sa.text(
                f"SELECT p.depth, count(*) FROM spider_pages p WHERE p.crawl_id = :crawl_id AND {OWN} GROUP BY p.depth"  # noqa: S608
            ),
            {"crawl_id": crawl_id},
        ).all()
    return {
        "folders": [
            {"folder": f, "urls": n, "indexable": indexable[f], "non_indexable": n - indexable[f]}
            for f, n in sorted(folders.items())
        ],
        "depths": {str(d): n for d, n in sorted(depths)},
    }


# --- response times --------------------------------------------------------------------------------

BUCKETS = (100, 200, 500, 1000, 2000, 5000)


def response_times(engine: sa.Engine, crawl_id: int, slowest: int = 20) -> dict:
    """Response Times: the site's URLs per band of response time, and the slowest ones."""
    bands = " ".join(f"WHEN response_ms < {b} THEN '<{b}'" for b in BUCKETS)
    params = {"crawl_id": crawl_id, "slowest": slowest}
    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(f"SELECT CASE {bands} ELSE '>={BUCKETS[-1]}' END AS band, count(*) FROM spider_pages p"  # noqa: S608
                    f" WHERE p.crawl_id = :crawl_id AND {OWN} AND response_ms IS NOT NULL GROUP BY band"),
            params,
        ).all()  # fmt: skip
        stats = conn.execute(
            sa.text(f"SELECT count(*), avg(response_ms), max(response_ms) FROM spider_pages p WHERE p.crawl_id = :crawl_id"  # noqa: S608
                    f" AND {OWN} AND response_ms IS NOT NULL"),
            params,
        ).one()  # fmt: skip
        slow = conn.execute(
            sa.text(f"SELECT url, response_ms, status_code FROM spider_pages p WHERE p.crawl_id = :crawl_id AND {OWN}"  # noqa: S608
                    " AND response_ms IS NOT NULL ORDER BY response_ms DESC LIMIT :slowest"),
            params,
        ).mappings()  # fmt: skip
        slowest_rows = [dict(r) for r in slow]
    order = [f"<{b}" for b in BUCKETS] + [f">={BUCKETS[-1]}"]
    counts = dict(rows)
    return {
        "urls": stats[0],
        "average_ms": round(stats[1]) if stats[1] is not None else None,
        "max_ms": stats[2],
        "bands": {band: counts.get(band, 0) for band in order},
        "slowest": slowest_rows,
    }


# --- crawl path ------------------------------------------------------------------------------------


def crawl_path(engine: sa.Engine, crawl_id: int, url: str) -> list[dict]:
    """Crawl Path: how the crawl reached a URL — from the start page, each step a URL one click shallower that links
    (or redirects, or canonicalises…) to the next."""
    step = sa.text(
        "SELECT s.url, l.kind, sp.depth FROM spider_urls t JOIN spider_link_rows l ON l.crawl_id = t.crawl_id AND l.target_id = t.id"
        " JOIN spider_urls s ON s.id = l.source_id JOIN spider_pages sp ON sp.crawl_id = t.crawl_id AND sp.url = s.url"
        " WHERE t.crawl_id = :crawl_id AND t.url = :url AND sp.depth = :depth ORDER BY l.kind <> 'hyperlink', s.url"
        " LIMIT 1"
    )
    with engine.connect() as conn:
        depth = conn.execute(
            sa.text("SELECT depth FROM spider_pages WHERE crawl_id = :crawl_id AND url = :url"),
            {"crawl_id": crawl_id, "url": url},
        ).scalar()
        if depth is None:
            raise InvalidArguments(f"No {url} in crawl #{crawl_id} — see 'spider urls' or 'spider query'.")
        path = [{"url": url, "depth": depth, "via": None}]
        current = url
        while depth > 0:
            found = conn.execute(step, {"crawl_id": crawl_id, "url": current, "depth": depth - 1}).first()
            if found is None:  # linked by something the crawl didn't store (e.g. collect.*.store off)
                break
            path[-1]["via"] = found.kind  # how this step was reached from the one before it
            current, depth = found.url, found.depth
            path.append({"url": current, "depth": depth, "via": None})
    return list(reversed(path))


# --- meta keywords, forms --------------------------------------------------------------------------

META_KEYWORDS = {
    "all": "p.meta_keywords IS NOT NULL",
    "missing": "p.meta_keywords_count = 0",
    "multiple": "p.meta_keywords_count > 1",
    "duplicate": "trim(coalesce(p.meta_keywords, '')) <> ''",  # and shared with another page: see meta_keywords()
}


def meta_keywords(engine: sa.Engine, crawl_id: int, only: str, limit: int | None = None) -> tuple[int, list[dict]]:
    """Meta Keywords tab: the HTML pages' keywords — all, missing, multiple tags, the same keywords on several pages."""
    if only not in META_KEYWORDS:
        raise InvalidArguments(f"--only: one of {', '.join(META_KEYWORDS)}.")
    query = (
        "SELECT url, keywords, tags FROM (SELECT p.url, p.meta_keywords AS keywords, p.meta_keywords_count AS tags,"  # noqa: S608
        " count(*) OVER (PARTITION BY p.meta_keywords) AS shared FROM spider_pages p"  # one pass: a window count per value
        f" WHERE p.crawl_id = :crawl_id AND {HTML_OK} AND {META_KEYWORDS[only]})"
        f"{' WHERE shared > 1' if only == 'duplicate' else ''} ORDER BY url"
    )
    return _rows(engine, query, {"crawl_id": crawl_id}, limit)


def forms(engine: sa.Engine, crawl_id: int, limit: int | None = None) -> tuple[int, list[dict]]:
    """Forms: every form's page and where it submits, and whether that's plain HTTP."""
    query = (
        "SELECT source AS page, target AS action, internal, target LIKE 'http://%' AS insecure FROM spider_links"
        " WHERE crawl_id = :crawl_id AND kind = 'form' ORDER BY source, target"
    )
    return _rows(engine, query, {"crawl_id": crawl_id}, limit)


# --- headers and cookies ---------------------------------------------------------------------------


def headers_summary(engine: sa.Engine, crawl_id: int, cookies: bool = False) -> list[dict]:
    """HTTP Header Summary (each response header and how many URLs send it) or Cookie Summary (each cookie name,
    its URLs and the attributes seen). Streams the pages; the counters hold one entry per distinct name."""
    names: Counter[str] = Counter()
    example: dict[str, str] = {}
    attributes: dict[str, set[str]] = {}
    query = sa.text(
        f"SELECT p.url, p.headers FROM spider_pages p WHERE p.crawl_id = :crawl_id AND {OWN} AND p.headers IS NOT NULL"  # noqa: S608
    )
    with engine.connect() as conn:
        for url, raw in storage.streamed(conn, 1000).execute(query, {"crawl_id": crawl_id}):
            headers = json.loads(raw)
            items = cookies_of(headers) if cookies else [{"name": name} for name in headers]
            for item in items:
                name = item["name"]
                names[name] += 1
                example.setdefault(name, url)
                if cookies:
                    attributes.setdefault(name, set()).update(k for k in item if k not in ("name", "value"))
    return [{"name": name, "urls": n, "example": example[name],
             **({"attributes": sorted(attributes[name])} if cookies else {})}
            for name, n in names.most_common()]  # fmt: skip


# --- javascript ------------------------------------------------------------------------------------

JAVASCRIPT = {
    # Chrome Console Log Summary: each console error / warning text and how many pages logged it
    "console": "SELECT kind, message, count(DISTINCT url) AS pages, min(url) AS example FROM spider_render_events"
    " WHERE crawl_id = :crawl_id AND kind IN ('error', 'warning') GROUP BY kind, message"
    " ORDER BY kind = 'warning', pages DESC, message",
    # resources the browser didn't get: robots.txt (Pages with Blocked Resources), failed, 4xx / 5xx
    "resources": "SELECT resource, kind, min(message) AS reason, count(DISTINCT url) AS pages, min(url) AS example"
    " FROM spider_render_events WHERE crawl_id = :crawl_id AND kind IN ('blocked', 'failed') GROUP BY resource, kind"
    " ORDER BY kind, pages DESC, resource",
}


def javascript(engine: sa.Engine, crawl_id: int, only: str, url: str | None = None,
               limit: int | None = None) -> tuple[int, list[dict]]:  # fmt: skip
    """Chrome Console Log Summary (`console`) or the resources rendering couldn't load (`resources`); with `url` —
    that page's own messages / resources, one row each."""
    if only not in JAVASCRIPT:
        raise InvalidArguments(f"--only: one of {', '.join(JAVASCRIPT)}.")
    if url is None:
        return _rows(engine, JAVASCRIPT[only], {"crawl_id": crawl_id}, limit)
    kinds = "('error', 'warning')" if only == "console" else "('blocked', 'failed')"
    query = (
        f"SELECT kind, message, resource FROM spider_render_events WHERE crawl_id = :crawl_id AND url = :url"  # noqa: S608
        f" AND kind IN {kinds} ORDER BY id"
    )
    return _rows(engine, query, {"crawl_id": crawl_id, "url": url}, limit)


# --- pagespeed (spider lighthouse) -----------------------------------------------------------------

PAGESPEED = {
    # Opportunities Summary: each failed audit — how many measured pages fail it
    "opportunities": "SELECT audit, count(DISTINCT url) AS pages, min(url) AS example FROM spider_lighthouse_audits"  # noqa: S608 — fixed audit ids
    " WHERE crawl_id = :crawl_id AND score < 0.9 AND audit IN ("
    + ", ".join(f"'{a}'" for a in CHECKED_AUDITS)
    + ") GROUP BY audit ORDER BY pages DESC, audit",
    # the pages measured, with their performance score (mobile / desktop)
    "pages": "SELECT url, strategy, score AS performance FROM spider_lighthouse_audits WHERE crawl_id = :crawl_id"
    " AND audit = 'category:performance' ORDER BY score, url",
}


def pagespeed(engine: sa.Engine, crawl_id: int, only: str, limit: int | None = None) -> tuple[int, list[dict]]:
    """PageSpeed Opportunities Summary or the measured pages' scores; `coverage` — CSS / JavaScript Coverage
    Summary: unused bytes per stylesheet / script, from the unused-css / unused-javascript audits' resources."""
    if only == "coverage":
        return _coverage(engine, crawl_id, limit)
    if only not in PAGESPEED:
        raise InvalidArguments(f"--only: one of {', '.join([*PAGESPEED, 'coverage'])}.")
    return _rows(engine, PAGESPEED[only], {"crawl_id": crawl_id}, limit)


def _coverage(engine: sa.Engine, crawl_id: int, limit: int | None) -> tuple[int, list[dict]]:
    """Unused bytes per resource, summed over the measured pages (the items are at most 20 per page: small)."""
    totals: dict[tuple[str, str], list[int]] = {}
    query = sa.text("SELECT audit, items FROM spider_lighthouse_audits WHERE crawl_id = :crawl_id AND items IS NOT NULL"
                    " AND audit IN ('unused-css-rules', 'unused-javascript')")  # fmt: skip
    with engine.connect() as conn:
        for audit, raw in conn.execute(query, {"crawl_id": crawl_id}):
            for item in json.loads(raw):
                if "url" in item:
                    entry = totals.setdefault(("css" if audit == "unused-css-rules" else "js", item["url"]), [0, 0, 0])
                    entry[0] += 1
                    entry[1] += int(item.get("wastedBytes") or 0)
                    entry[2] += int(item.get("totalBytes") or 0)
    rows = [{"kind": kind, "resource": url, "pages": n, "unused_bytes": wasted, "total_bytes": total}
            for (kind, url), (n, wasted, total) in sorted(totals.items(), key=lambda kv: -kv[1][1])]  # fmt: skip
    return len(rows), rows[: limit or None]
