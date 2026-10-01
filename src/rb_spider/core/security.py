"""Security: the Insecure Content report and HTTP / HTTPS counts — Screaming Frog's Security tab and report.

HTTPS pages that link to or load something over plain HTTP. Found through the crawl's http:// URLs (by URL id,
via the index on links' targets) and only when the crawl has any https:// page at all, so an HTTP-only site
costs nothing here. The checks are rules in `issues`.
"""

from __future__ import annotations

import sqlalchemy as sa

from . import storage

RESOURCES = "('image', 'css', 'js', 'media', 'iframe')"
# http:// URLs of the crawl, when it has https:// pages to link to them from (GLOB: case-sensitive, uses the index)
HTTP_TARGETS = (
    "SELECT id FROM spider_urls WHERE crawl_id = :crawl_id AND url GLOB 'http://*'"
    " AND EXISTS (SELECT 1 FROM spider_urls x WHERE x.crawl_id = :crawl_id AND x.url GLOB 'https://*')"
)


def insecure_links(kinds: str | None = None) -> str:
    """Rows (source, kind, target) of HTTPS pages pointing at HTTP URLs; `kinds` — an SQL list to narrow to."""
    only = f" AND l.kind IN {kinds}" if kinds else ""
    return (
        f"SELECT s.url AS source, l.kind, t.url AS target FROM ({HTTP_TARGETS}) h"  # noqa: S608 — fixed text
        " JOIN spider_link_rows l ON l.crawl_id = :crawl_id AND l.target_id = h.id"
        " JOIN spider_urls s ON s.id = l.source_id JOIN spider_urls t ON t.id = l.target_id"
        f" WHERE s.url GLOB 'https://*'{only}"
    )


def insecure_content(engine: sa.Engine, crawl_id: int, limit: int | None = None) -> tuple[int, list[dict]]:
    """Every link and resource from an HTTPS page to an HTTP URL: the total and the first `limit`."""
    query = insecure_links()
    with engine.connect() as conn:
        total = conn.execute(sa.text(f"SELECT count(*) FROM ({query})"), {"crawl_id": crawl_id}).scalar_one()  # noqa: S608
        rows = conn.execute(
            sa.text(f"{query} ORDER BY source, target LIMIT :limit"),
            {"crawl_id": crawl_id, "limit": storage.NO_LIMIT if limit is None else limit},
        ).mappings()
        return total, [dict(row) for row in rows]


def counts(conn: sa.Connection, crawl_id: int) -> dict[str, int]:
    """The site's URLs by scheme — Screaming Frog's HTTPS URLs / HTTP URLs filters."""
    rows = conn.execute(
        sa.text(
            "SELECT substr(url, 1, instr(url, ':') - 1) AS scheme, count(*) FROM spider_pages WHERE crawl_id = :crawl_id"
            " AND NOT coalesce(external, FALSE) GROUP BY scheme ORDER BY scheme"
        ),
        {"crawl_id": crawl_id},
    )
    return {scheme: n for scheme, n in rows}
