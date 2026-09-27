"""Pagination (rel next / prev): the Pagination report, the overview counts and loop detection.

Series are link rows of kinds "next" / "prev" (from `<link rel>` and the `Link` header) plus the page's own
place in its series, `pages.pagination` ("first" — next only, "paginated" — has prev). Queries say
`kind IN ('next', 'prev')` so SQLite uses the partial index over those rows. The checks are rules in `issues`.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal, get_args

import sqlalchemy as sa

from . import storage

PAGINATION = "l.kind IN ('next', 'prev')"
Only = Literal["all", "non_200", "unlinked"]
ONLY: tuple[str, ...] = get_args(Only)

_ROWS = """
    SELECT s.url AS source, l.kind AS rel, t.url AS target, p.status_code AS target_status,
           p.blocked AS target_blocked, p.indexability_status AS target_indexability
    FROM link_rows l JOIN urls s ON s.id = l.source_id JOIN urls t ON t.id = l.target_id
    LEFT JOIN pages p ON p.crawl_id = l.crawl_id AND p.url = t.url
    WHERE l.crawl_id = :crawl_id AND l.kind IN ('next', 'prev')
"""
FILTERS = {
    "all": "TRUE",
    "non_200": "p.url IS NOT NULL AND (p.status_code <> 200 OR p.blocked IS NOT NULL)",
    "unlinked": "NOT coalesce(p.external, TRUE) AND NOT EXISTS (SELECT 1 FROM link_rows h WHERE h.crawl_id = l.crawl_id"
    " AND h.target_id = l.target_id AND h.kind = 'hyperlink')",
    "not_in_anchor": "NOT EXISTS (SELECT 1 FROM link_rows h WHERE h.crawl_id = l.crawl_id AND h.source_id = l.source_id"
    " AND h.target_id = l.target_id AND h.kind = 'hyperlink')",
    # A.next = B, yet B (read, 200) doesn't point back with prev — or the other way round
    "sequence_error": "p.parsed AND p.status_code = 200 AND NOT EXISTS (SELECT 1 FROM link_rows b"
    " WHERE b.crawl_id = l.crawl_id AND b.kind IN ('next', 'prev') AND b.source_id = l.target_id"
    " AND b.target_id = l.source_id AND b.kind <> l.kind)",
}


def report(engine: sa.Engine, crawl_id: int, only: str = "all", limit: int | None = None) -> tuple[int, list[dict]]:
    """rel next / prev links matching `only` (see ONLY): the total and the first `limit` rows."""
    query = f"{_ROWS} AND ({FILTERS[only]})"
    with engine.connect() as conn:
        total = conn.execute(sa.text(f"SELECT count(*) FROM ({query})"), {"crawl_id": crawl_id}).scalar_one()  # noqa: S608 — fixed text
        rows = conn.execute(
            sa.text(f"{query} ORDER BY source, rel, target LIMIT :limit"),
            {"crawl_id": crawl_id, "limit": storage.NO_LIMIT if limit is None else limit},
        ).mappings()
        return total, [dict(row) for row in rows]


def counts(conn: sa.Connection, crawl_id: int) -> dict[str, int]:
    """Screaming Frog's Contains Pagination / First Page / Paginated 2+ Pages, over the site's pages."""
    rows = conn.execute(
        sa.text(
            "SELECT pagination, count(*) FROM pages WHERE crawl_id = :crawl_id AND NOT coalesce(external, FALSE)"
            " AND pagination IS NOT NULL GROUP BY pagination"
        ),
        {"crawl_id": crawl_id},
    )
    found: dict[str, int] = {kind: n for kind, n in rows}
    if not found:
        return {}
    first, paginated = found.get("first", 0), found.get("paginated", 0)
    return {"contains": first + paginated, "first_page": first, "paginated": paginated}


def looping(conn: sa.Connection, crawl_id: int) -> Iterator[tuple[str, str]]:
    """Pages whose chain of rel=next (or of rel=prev) comes back to a page already passed: (url, the loop).

    One edge per page and direction (the first, as a search engine would read it), by URL id — ints, not URL
    strings, even for a site with a very long series. Each graph is walked once (visited pages are coloured).
    """
    for rel in ("next", "prev"):
        edges: dict[int, int] = {
            source: target
            for source, target in conn.execute(
                sa.text(
                    "SELECT source_id, min(target_id) FROM link_rows l WHERE l.crawl_id = :crawl_id"
                    " AND l.kind IN ('next', 'prev') AND l.kind = :rel GROUP BY source_id"
                ),
                {"crawl_id": crawl_id, "rel": rel},
            )
        }
        done: set[int] = set()
        on_cycle: dict[int, list[int]] = {}
        for start in edges:
            path, index = [], {}
            node: int | None = start
            while node is not None and node not in done and node not in index:
                index[node] = len(path)
                path.append(node)
                node = edges.get(node)
            if node is not None and node in index:  # came back into this walk: a cycle
                cycle = path[index[node] :]
                for member in cycle:
                    on_cycle[member] = cycle
            done.update(path)
        if on_cycle:
            ids = sorted({i for cycle in on_cycle.values() for i in cycle})
            query = sa.text("SELECT id, url FROM urls WHERE id IN :ids").bindparams(sa.bindparam("ids", expanding=True))
            urls: dict[int, str] = {i: url for i, url in conn.execute(query, {"ids": ids})}
            for member, cycle in on_cycle.items():
                yield urls[member], f"{rel}: " + " → ".join(urls[i] for i in [*cycle, cycle[0]])
