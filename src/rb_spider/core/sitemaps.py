"""XML sitemaps through the sibling package rb-sitemap-xml (extra `rb-spider[sitemaps]`): read at the start of a
crawl, reported after it, and generated from it.

Reading streams: `SitemapClient.iter_files` hands over one file at a time; its entries go to `sitemap_urls` with
the next batch of the crawl's writer and into the queue (`sitemaps.follow`), hreflang alternates become link rows
of kind "hreflang". Checks are rules in `issues`; the limits (50 000 URLs, 50 MB) are thresholds.
"""

from __future__ import annotations

import importlib.util
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Literal, get_args
from urllib.parse import urlsplit

import sqlalchemy as sa

from . import storage
from .errors import InvalidArguments, SitemapsUnavailable
from .extract import normalize_url
from .scope import Scope, link_row
from .settings import CrawlSettings, SitemapSettings


def ensure_available() -> None:
    if importlib.util.find_spec("rb_sitemap_xml") is None:
        raise SitemapsUnavailable


async def read(
    start_url: str,
    settings: SitemapSettings,
    crawl: CrawlSettings,
    writer: storage.PageWriter,
    scope: Scope,
) -> AsyncIterator[list[str]]:
    """Every sitemap of the site, one file at a time: stored with the writer, its URLs yielded for the queue."""
    from loguru import logger  # rb-sitemap-xml logs with loguru: its progress lines are noise in a crawl
    from rb_sitemap_xml import SitemapClient, SitemapError

    logger.disable("rb_sitemap_xml")
    options: dict = {"timeout": crawl.timeout_s, "verify": crawl.verify_tls}
    if crawl.resolved_user_agent:
        options["user_agent"] = crawl.resolved_user_agent
    client = SitemapClient(**options)
    found = list(settings.urls)
    if settings.discover:
        try:
            found += await client.discover(start_url)
        except SitemapError as exc:
            if not found:
                origin = "{0.scheme}://{0.netloc}".format(urlsplit(start_url))
                writer.sitemap({"url": f"{origin}/sitemap.xml", "error": str(exc)[:500]}, [])
    if not found:
        return
    try:
        async for file, entries in client.iter_files(sitemap_urls=list(dict.fromkeys(found))):
            locs = [(normalize_url(entry.loc), entry.lastmod) for entry in entries]
            writer.sitemap(file.model_dump(), locs)
            writer.add_links([
                link_row(url, normalize_url(href), "hreflang", scope.internal(href), hreflang=code)
                for (url, _), entry in zip(locs, entries, strict=True) for code, href in entry.alternates
            ])  # fmt: skip
            yield [url for url, _ in locs]
    except SitemapError as exc:  # more nested sitemaps than rb-sitemap-xml's limit
        writer.sitemap({"url": found[0], "error": str(exc)[:500]}, [])


# --- report ----------------------------------------------------------------------------------------

Only = Literal["files", "urls", "orphans", "not_in_sitemap"]
ONLY: tuple[str, ...] = get_args(Only)
_OWN_PAGE = "LEFT JOIN pages p ON p.crawl_id = s.crawl_id AND p.url = s.url"
QUERIES = {
    "files": "SELECT url, kind, bytes, urls, sitemaps, error FROM sitemap_files WHERE crawl_id = :crawl_id",
    "urls": (
        "SELECT s.url, s.source, s.lastmod, p.status_code, p.indexability_status FROM sitemap_urls s "  # noqa: S608
        f"{_OWN_PAGE} WHERE s.crawl_id = :crawl_id"
    ),
    # in a sitemap, no <a href> to it anywhere on the site (and, with sitemaps.follow off, maybe never crawled)
    "orphans": (
        "SELECT s.url, min(s.source) AS source, p.status_code, p.indexability_status FROM sitemap_urls s "  # noqa: S608
        f"{_OWN_PAGE} WHERE s.crawl_id = :crawl_id AND NOT coalesce(p.external, FALSE) AND NOT EXISTS ("
        " SELECT 1 FROM urls u JOIN link_rows l ON l.crawl_id = u.crawl_id AND l.target_id = u.id"
        " AND l.kind = 'hyperlink' WHERE u.crawl_id = s.crawl_id AND u.url = s.url) GROUP BY s.url, p.status_code, p.indexability_status"
    ),
    # indexable HTML pages of the site that no sitemap lists
    "not_in_sitemap": (
        "SELECT p.url, p.depth, p.inlinks FROM pages p WHERE p.crawl_id = :crawl_id AND NOT coalesce(p.external, FALSE)"
        " AND p.parsed AND p.status_code = 200 AND p.content_type LIKE '%html%' AND p.indexable AND NOT EXISTS ("
        " SELECT 1 FROM sitemap_urls s WHERE s.crawl_id = p.crawl_id AND s.url = p.url)"
    ),
}


def report(engine: sa.Engine, crawl_id: int, only: str, limit: int | None = None) -> tuple[int, list[dict]]:
    query = QUERIES[only]
    with engine.connect() as conn:
        total = conn.execute(sa.text(f"SELECT count(*) FROM ({query})"), {"crawl_id": crawl_id}).scalar_one()  # noqa: S608
        rows = conn.execute(
            sa.text(f"SELECT * FROM ({query}) ORDER BY url LIMIT :limit"),  # noqa: S608
            {"crawl_id": crawl_id, "limit": storage.NO_LIMIT if limit is None else limit},
        ).mappings()
        return total, [dict(row) for row in rows]


def counts(conn: sa.Connection, crawl_id: int) -> dict[str, int]:
    """Sitemap files and URLs, and the site's pages in and out of them — Screaming Frog's Sitemaps filters."""
    files, urls = conn.execute(
        sa.text(
            "SELECT (SELECT count(*) FROM sitemap_files WHERE crawl_id = :crawl_id),"
            " (SELECT count(DISTINCT url) FROM sitemap_urls WHERE crawl_id = :crawl_id)"
        ),
        {"crawl_id": crawl_id},
    ).one()
    if not files:
        return {}
    params = {"crawl_id": crawl_id}
    not_in = conn.execute(sa.text(f"SELECT count(*) FROM ({QUERIES['not_in_sitemap']})"), params).scalar_one()  # noqa: S608
    orphans = conn.execute(sa.text(f"SELECT count(*) FROM ({QUERIES['orphans']})"), params).scalar_one()  # noqa: S608
    return {"files": files, "urls": urls, "not_in_sitemap": not_in, "orphans": orphans}


# --- generation ------------------------------------------------------------------------------------

INCLUDE = ("noindex", "canonicalised", "paginated", "pdf")


def _pages_query(include: set[str]) -> str:
    """The pages a sitemap lists: the site's 200 HTML pages that are indexable, plus what `include` allows."""
    kinds = "p.content_type LIKE '%html%'" + (" OR p.content_type LIKE '%pdf%'" if "pdf" in include else "")
    allowed = ["p.indexable"]
    if "noindex" in include:
        allowed.append("p.indexability_status = 'noindex'")
    if "canonicalised" in include:
        allowed.append("p.indexability_status = 'Canonicalised'")
    paginated = "" if "paginated" in include else " AND coalesce(p.pagination, '') <> 'paginated'"
    return (
        "SELECT p.url, p.last_modified, p.depth FROM pages p WHERE p.crawl_id = :crawl_id AND NOT coalesce(p.external, FALSE)"  # noqa: S608
        f" AND p.status_code = 200 AND ({kinds}) AND ({' OR '.join(allowed)}){paginated} ORDER BY p.url"
    )


CHANGEFREQ = ("always", "hourly", "daily", "weekly", "monthly", "yearly", "never")


def _priority(value: str | None) -> float | None:
    """`--priority`: None, "depth" (1.0 at the start page, 0.1 less a click deeper) or a fixed 0.0–1.0."""
    if value is None or value == "depth":
        return None
    try:
        number = float(value)
    except ValueError:
        number = -1.0
    if not 0 <= number <= 1:
        raise InvalidArguments("--priority: a number from 0.0 to 1.0, or depth.")
    return number


def _iso_date(http_date: str | None) -> str | None:
    """`Last-Modified: Wed, 01 Jan 2025 10:00:00 GMT` → 2025-01-01."""
    from email.utils import parsedate_to_datetime

    try:
        return parsedate_to_datetime(http_date).date().isoformat() if http_date else None
    except (TypeError, ValueError):
        return None


def build(
    engine: sa.Engine,
    crawl_id: int,
    out_dir: Path,
    *,
    base_url: str,
    include: set[str],
    lastmod: bool,
    images: bool,
    changefreq: str | None = None,
    priority: str | None = None,
) -> tuple[list[Path], int]:
    """Write a sitemap (or, `images`, an image sitemap) of a crawl with rb-sitemap-xml; returns (files, URLs).

    Pages stream from the database to the files: memory stays flat whatever the size of the site.
    """
    ensure_available()
    from rb_sitemap_xml import SitemapEntry, write_sitemaps

    unknown = include - set(INCLUDE)
    if unknown:
        raise InvalidArguments(f"--include: unknown {', '.join(sorted(unknown))}; one of {', '.join(INCLUDE)}.")
    if changefreq is not None and changefreq not in CHANGEFREQ:
        raise InvalidArguments(f"--changefreq: one of {', '.join(CHANGEFREQ)}.")
    fixed = _priority(priority)
    count = 0

    def entries(conn: sa.Connection) -> Iterator[SitemapEntry]:
        nonlocal count
        rows = storage.streamed(conn, 1000).execute(sa.text(_pages_query(include)), {"crawl_id": crawl_id})
        for url, last_modified, depth in rows:
            pictures: list[str] = []
            if images:
                pictures = list(conn.execute(sa.text(
                    "SELECT DISTINCT t.url FROM urls s JOIN link_rows l ON l.crawl_id = s.crawl_id AND l.source_id = s.id"
                    " AND l.kind = 'image' JOIN urls t ON t.id = l.target_id JOIN pages ip ON ip.crawl_id = s.crawl_id"
                    " AND ip.url = t.url AND ip.status_code = 200 WHERE s.crawl_id = :crawl_id AND s.url = :url"
                    " ORDER BY t.url"), {"crawl_id": crawl_id, "url": url}).scalars())  # fmt: skip
                if not pictures:
                    continue
            count += 1
            rank = max(1.0 - 0.1 * depth, 0.1) if priority == "depth" else fixed
            yield SitemapEntry(loc=url, lastmod=_iso_date(last_modified) if lastmod else None, images=pictures,
                               changefreq=changefreq, priority=rank)  # fmt: skip

    with engine.connect() as conn:
        files = write_sitemaps(entries(conn), out_dir, base_url=base_url, name="image-sitemap" if images else "sitemap")
    return files, count
