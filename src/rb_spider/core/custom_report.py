"""The Custom Search / Custom Extraction report over a stored crawl: every rule with its page counts, or one rule's
pages. Search rows exist only where there were matches, so "does not contain" is the site's HTML pages without one.
"""

from __future__ import annotations

import sqlalchemy as sa

from . import storage
from .errors import InvalidArguments
from .settings import Settings

HTML_PAGES = (
    "SELECT url FROM pages WHERE crawl_id = :crawl_id AND NOT coalesce(external, FALSE) AND parsed AND status_code = 200"
    " AND content_type LIKE '%html%'"
)


def rules(engine: sa.Engine, crawl_id: int) -> list[dict]:
    """The crawl's rules (from its settings) with the pages that matched / had values and, for searches, the rest."""
    _, snapshot = storage.get_crawl(engine, crawl_id)
    custom = Settings.model_validate(snapshot or {}).custom
    counts = sa.text(
        "SELECT kind, name, count(DISTINCT url) FROM custom_values WHERE crawl_id = :crawl_id GROUP BY kind, name"
    )
    with engine.connect() as conn:
        found = {(kind, name): n for kind, name, n in conn.execute(counts, {"crawl_id": crawl_id})}
        html = conn.execute(sa.text(f"SELECT count(*) FROM ({HTML_PAGES})"), {"crawl_id": crawl_id}).scalar_one()  # noqa: S608
    listed = [("search", rule.name) for rule in custom.search] + [("extract", rule.name) for rule in custom.extract]
    return [{"kind": kind, "name": name, "pages": found.get((kind, name), 0),
             "without": html - found.get((kind, name), 0) if kind == "search" else None}
            for kind, name in listed]  # fmt: skip


def rows(
    engine: sa.Engine, crawl_id: int, kind: str, name: str, *, without: bool = False, limit: int | None = None
) -> tuple[int, list[dict]]:
    """One rule's pages: a search — the pages with matches (`n` — how many) or, `without`, the HTML pages with none;
    an extraction — each value (`n` — its order on the page)."""
    if without and kind != "search":
        raise InvalidArguments("--without lists pages a search found nothing on: use it with --search.")
    params = {"crawl_id": crawl_id, "kind": kind, "name": name, "limit": storage.NO_LIMIT if limit is None else limit}
    if without:
        query = (f"SELECT url FROM ({HTML_PAGES}) h WHERE NOT EXISTS (SELECT 1 FROM custom_values c"  # noqa: S608
                 " WHERE c.crawl_id = :crawl_id AND c.kind = :kind AND c.name = :name AND c.url = h.url)")  # fmt: skip
    else:
        query = ("SELECT url, value, n FROM custom_values WHERE crawl_id = :crawl_id AND kind = :kind"
                 " AND name = :name")  # fmt: skip
    with engine.connect() as conn:
        total = conn.execute(sa.text(f"SELECT count(*) FROM ({query})"), params).scalar_one()  # noqa: S608
        found = conn.execute(sa.text(f"{query} ORDER BY url LIMIT :limit"), params).mappings()
        return total, [dict(row) for row in found]
