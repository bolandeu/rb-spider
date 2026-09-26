"""A crawl at a glance — Screaming Frog's Crawl Overview and right-hand Overview panel.

Counts only, each a single grouped SQL pass over the crawl's pages, so the size of the site doesn't
matter. Every number has a command that lists its URLs (`spider export pages --type css`, `--status 4xx`,
`spider urls --issue …`); the command's help says which.
"""

from __future__ import annotations

import sqlalchemy as sa

from .extract import DIRECTIVES

# What a URL is, from its Content-Type — Screaming Frog's Internal / External filters.
CONTENT_KINDS = ("html", "js", "css", "image", "pdf", "other", "unknown")
CONTENT_KIND_SQL = """CASE
    WHEN content_type IS NULL OR content_type = '' THEN 'unknown'
    WHEN content_type LIKE '%html%' THEN 'html'
    WHEN content_type LIKE '%javascript%' OR content_type LIKE '%ecmascript%' THEN 'js'
    WHEN content_type LIKE '%css%' THEN 'css'
    WHEN content_type LIKE 'image/%' THEN 'image'
    WHEN content_type LIKE '%pdf%' THEN 'pdf'
    ELSE 'other' END"""
_OWN = "NOT coalesce(external, 0)"


def _counts(conn: sa.Connection, crawl_id: int, expression: str, where: str = _OWN) -> dict[str, int]:
    query = (
        f"SELECT {expression} AS k, count(*) FROM pages WHERE crawl_id = :crawl_id AND {where} GROUP BY k ORDER BY k"  # noqa: S608 — fixed text
    )
    return {str(key): n for key, n in conn.execute(sa.text(query), {"crawl_id": crawl_id})}


def overview(engine: sa.Engine, crawl_id: int) -> dict:
    status_class = """CASE WHEN blocked IS NOT NULL THEN 'blocked' WHEN status_code = 0 THEN 'no_response'
        ELSE (status_code / 100) || 'xx' END"""
    canonical = """CASE WHEN canonical_url IS NULL THEN 'missing' WHEN canonical_url = url THEN 'self_referencing'
        ELSE 'canonicalised' END"""
    html_ok = f"{_OWN} AND parsed AND status_code = 200 AND content_type LIKE '%html%'"
    with engine.connect() as conn:
        totals = conn.execute(
            sa.text(
                f"SELECT count(*), sum({_OWN}), sum(coalesce(external, 0)), sum(blocked IS NOT NULL),"  # noqa: S608
                " sum(status_code = 0 AND blocked IS NULL), sum(coalesce(indexable, 0)) FROM pages"
                " WHERE crawl_id = :crawl_id"
            ),
            {"crawl_id": crawl_id},
        ).one()
        queued = conn.execute(
            sa.text("SELECT count(*), sum(NOT done) FROM frontier WHERE crawl_id = :crawl_id"), {"crawl_id": crawl_id}
        ).one()
        directives = {}
        for name in sorted(DIRECTIVES):
            n = conn.execute(
                sa.text(
                    f"SELECT count(*) FROM pages WHERE crawl_id = :crawl_id AND {html_ok}"  # noqa: S608
                    " AND robots_directives LIKE :token"
                ),
                {"crawl_id": crawl_id, "token": f"%,{name},%"},
            ).scalar_one()
            if n:
                directives[name] = n
        data = {
            "crawl_id": crawl_id,
            "totals": {
                "stored": totals[0],
                "internal": totals[1] or 0,
                "external": totals[2] or 0,
                "blocked_by_robots": totals[3] or 0,
                "no_response": totals[4] or 0,
                "indexable": totals[5] or 0,
                "queued_ever": queued[0] or 0,
                "still_queued": queued[1] or 0,
            },
            "content_types": _counts(conn, crawl_id, CONTENT_KIND_SQL),
            "external_content_types": _counts(conn, crawl_id, CONTENT_KIND_SQL, "coalesce(external, 0)"),
            "status": _counts(conn, crawl_id, status_class),
            "indexability": _counts(conn, crawl_id, "coalesce(indexability_status, 'Indexable')"),
            "canonicals": _counts(conn, crawl_id, canonical, html_ok),
            "directives": directives,
            "depth": _counts(conn, crawl_id, "depth", html_ok),
        }
    return data
