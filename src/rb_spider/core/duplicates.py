"""Near duplicates and the Duplicate Details report.

Near duplicates come from the MinHash signatures the crawl stored (`collect.near_duplicates`): LSH bands of
every signature go to a temporary table, pages sharing a band become candidates in SQL, each candidate pair is
checked against the similarity threshold, and pairs that pass are kept in `near_duplicates`. Nothing but a
batch of signatures is ever in memory. A band shared by a big template (thousands of alike pages) would give
millions of pairs, so within a band each page is compared with its next WINDOW neighbours only: a page's count
of near duplicates is then a lower bound — still far over any threshold worth reading.
"""

from __future__ import annotations

import difflib
import re

import sqlalchemy as sa

from . import content, storage
from .settings import ThresholdSettings

WINDOW = 50
_BATCH = 5000
HTML_OK = "NOT coalesce(external, 0) AND parsed AND status_code = 200 AND content_type LIKE '%html%'"
# the pages duplicate checks compare — thresholds.duplicates_indexable_only / ignore_paginated_duplicates
AMONG = (
    f"{HTML_OK} AND (indexable OR NOT :duplicates_indexable_only)"
    " AND NOT (:ignore_paginated_duplicates AND coalesce(pagination, '') = 'paginated')"
)


def _params(crawl_id: int, thresholds: ThresholdSettings) -> dict:
    return {
        "crawl_id": crawl_id,
        "duplicates_indexable_only": thresholds.duplicates_indexable_only,
        "ignore_paginated_duplicates": thresholds.ignore_paginated_duplicates,
    }


def compute_near(conn: sa.Connection, crawl_id: int, thresholds: ThresholdSettings) -> None:
    """Refill `near_duplicates` for a crawl from its pages' signatures (nothing to do for a crawl without them)."""
    conn.execute(sa.delete(storage.near_duplicates).where(storage.near_duplicates.c.crawl_id == crawl_id))
    params = _params(crawl_id, thresholds)
    has_signatures = conn.execute(
        sa.text("SELECT 1 FROM pages WHERE crawl_id = :crawl_id AND minhash IS NOT NULL LIMIT 1"), params
    ).first()
    if not has_signatures:
        return
    threshold = thresholds.near_duplicate_similarity / 100
    bands, rows = content.bands_for(threshold)
    conn.exec_driver_sql("DROP TABLE IF EXISTS temp.near_bands")
    conn.exec_driver_sql("CREATE TEMP TABLE near_bands (band INTEGER, h INTEGER, page INTEGER)")
    select = sa.text(
        f"SELECT rowid, minhash FROM pages WHERE crawl_id = :crawl_id AND {AMONG} AND minhash IS NOT NULL"  # noqa: S608
        " AND rowid > :after ORDER BY rowid LIMIT :limit"
    )
    after = 0
    while batch := conn.execute(select, params | {"after": after, "limit": _BATCH}).all():
        conn.exec_driver_sql(
            "INSERT INTO near_bands (band, h, page) VALUES (?, ?, ?)",
            [
                (band, h, rowid)
                for rowid, sig in batch
                for band, h in content.band_hashes(content.unpack(sig), bands, rows)
            ],
        )
        after = batch[-1][0]
    conn.exec_driver_sql("CREATE INDEX temp.near_bands_by_bucket ON near_bands (band, h, page)")
    # candidate pairs: pages sharing a band bucket, each page with its next WINDOW neighbours in the bucket;
    # a temporary table too — however many there are, they are read back a batch at a time
    conn.exec_driver_sql("DROP TABLE IF EXISTS temp.near_pairs")
    conn.execute(
        sa.text(
            "CREATE TEMP TABLE near_pairs AS"
            " WITH b AS (SELECT band, h, page, row_number() OVER (PARTITION BY band, h ORDER BY page) AS n"
            "  FROM near_bands)"
            " SELECT DISTINCT x.page AS a, y.page AS b FROM b x JOIN b y ON y.band = x.band AND y.h = x.h"
            "  AND y.n > x.n AND y.n <= x.n + :window"
        ),
        {"window": WINDOW},
    )
    conn.exec_driver_sql("DROP TABLE temp.near_bands")
    lookup = sa.text("SELECT rowid, url, minhash FROM pages WHERE rowid IN :ids").bindparams(
        sa.bindparam("ids", expanding=True)
    )
    next_pairs = sa.text("SELECT rowid, a, b FROM temp.near_pairs WHERE rowid > :after ORDER BY rowid LIMIT :limit")
    after = 0
    while chunk := conn.execute(next_pairs, {"after": after, "limit": _BATCH}).all():
        after = chunk[-1][0]
        pages = {rowid: (url, content.unpack(sig)) for rowid, url, sig in
                 conn.execute(lookup, {"ids": sorted({i for _, a, b in chunk for i in (a, b)})})}  # fmt: skip
        found = []
        for _, a, b in chunk:
            (url_a, sig_a), (url_b, sig_b) = sorted((pages[a], pages[b]), key=lambda page: page[0])
            if (score := content.similarity(sig_a, sig_b)) >= threshold:
                found.append({"crawl_id": crawl_id, "url_a": url_a, "url_b": url_b, "similarity": round(score, 3)})
        if found:
            conn.execute(sa.insert(storage.near_duplicates), found)
    conn.exec_driver_sql("DROP TABLE temp.near_pairs")


NEAR_FINDINGS = (
    "SELECT url, n || ' почти-дубл., ближайший ' || CAST(round(100 * best) AS INTEGER) || '% — ' || closest FROM ("
    "  SELECT url, count(*) AS n, max(similarity) AS best,"
    "   (SELECT other FROM pairs p2 WHERE p2.url = p.url ORDER BY similarity DESC, other LIMIT 1) AS closest"
    "  FROM pairs p GROUP BY url) ORDER BY url"
)
PAIRS = (
    "WITH pairs AS (SELECT url_a AS url, url_b AS other, similarity FROM near_duplicates WHERE crawl_id = :crawl_id"
    " UNION ALL SELECT url_b, url_a, similarity FROM near_duplicates WHERE crawl_id = :crawl_id) "
)

# --- Duplicate Details ---------------------------------------------------------------------------

_EXACT = (
    "SELECT url, first_value(url) OVER (PARTITION BY content_md5 ORDER BY url) AS other, 1.0 AS similarity,"  # noqa: S608
    " 'exact' AS kind, count(*) OVER (PARTITION BY content_md5) AS n FROM pages"
    f" WHERE crawl_id = :crawl_id AND {AMONG} AND content_md5 IS NOT NULL"
)


def report(
    engine: sa.Engine,
    crawl_id: int,
    thresholds: ThresholdSettings,
    *,
    kind: str = "all",
    url: str | None = None,
    limit: int | None = None,
) -> tuple[int, list[dict]]:
    """Duplicate pairs: exact (a page and the first page of its identical group) and near (each pair once).

    `url` — only pairs with that page; `kind` — all | exact | near. Returns the total and the first `limit`.
    """
    exact = f"SELECT url, other, similarity, kind FROM ({_EXACT}) WHERE n > 1 AND url <> other"  # noqa: S608
    near = "SELECT url_a AS url, url_b AS other, similarity, 'near' AS kind FROM near_duplicates WHERE crawl_id = :crawl_id"
    parts = {"all": [exact, near], "exact": [exact], "near": [near]}[kind]
    query = " UNION ALL ".join(f"SELECT * FROM ({part})" for part in parts)  # noqa: S608
    where = " WHERE url = :url OR other = :url" if url else ""
    params = _params(crawl_id, thresholds) | {"url": url, "limit": -1 if limit is None else limit}
    with engine.connect() as conn:
        total = conn.execute(sa.text(f"SELECT count(*) FROM ({query}){where}"), params).scalar_one()  # noqa: S608
        rows = conn.execute(
            sa.text(f"SELECT * FROM ({query}){where} ORDER BY kind, similarity DESC, url, other LIMIT :limit"),  # noqa: S608
            params,
        ).mappings()
        return total, [dict(row) for row in rows]


_SENTENCES = re.compile(r"(?<=[.!?…])\s+")


def text_diff(crawl_id: int, url: str, other: str, max_lines: int = 200) -> list[str] | None:
    """A unified diff of two pages' visible text, sentence by sentence — needs the crawl's stored HTML."""
    from .extract import visible_text

    bodies = [storage.get_html(crawl_id, u) for u in (url, other)]
    if any(body is None for body in bodies):
        return None
    texts = [_SENTENCES.split(visible_text(body or b"")) for body in bodies]
    diff = difflib.unified_diff(texts[0], texts[1], fromfile=url, tofile=other, lineterm="", n=1)
    return list(diff)[:max_lines]
