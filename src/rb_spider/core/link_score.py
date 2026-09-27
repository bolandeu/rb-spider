"""Link Score (Screaming Frog): each internal URL's share of the site's internal PageRank, on a 0–100 scale.

PageRank over the site's pages (HTML, or reached by a link) and their own follow <a href> links (each distinct source → target pair once, self-links aside), with
the usual damping 0.85 and the rank of pages without outlinks spread over every page. Computed in the database, a
pass over the links per iteration through temporary tables: nothing proportional to the site is held in Python.
The scale is logarithmic, like Screaming Frog's: the best-linked URL gets 100, the least 1.
"""

from __future__ import annotations

import math

import sqlalchemy as sa

from . import storage
from .settings import ThresholdSettings

DAMPING = 0.85
ITERATIONS = 20  # enough for the order of pages to settle on sites of any size
_BATCH = 5000


def compute(conn: sa.Connection, crawl_id: int, thresholds: ThresholdSettings) -> None:
    """Refill `pages.link_score` for a crawl (NULL everywhere while thresholds.link_score is off)."""
    conn.execute(sa.text("UPDATE pages SET link_score = NULL WHERE crawl_id = :c"), {"c": crawl_id})
    if not thresholds.link_score:
        return
    sqlite = storage.is_sqlite(conn)
    temp = "temp" if sqlite else "pg_temp"
    index = "temp." if sqlite else ""
    run = conn.exec_driver_sql
    for table in ("ls_nodes", "ls_edges", "ls_in"):
        run(f"DROP TABLE IF EXISTS {temp}.{table}")
    params = {"c": crawl_id}
    run("CREATE TEMP TABLE ls_nodes (id BIGINT PRIMARY KEY, score DOUBLE PRECISION, outdeg BIGINT)")
    conn.execute(sa.text(
        "INSERT INTO ls_nodes (id, score, outdeg) SELECT u.id, 0, 0 FROM urls u JOIN pages p ON p.crawl_id = u.crawl_id"
        " AND p.url = u.url WHERE u.crawl_id = :c AND NOT coalesce(p.external, FALSE)"
        # the site's pages: HTML, or linked like one (a redirect, a 404) — not the scripts and images they load
        " AND (p.content_type LIKE '%html%' OR p.inlinks > 0)"), params)  # fmt: skip
    n = conn.execute(sa.text("SELECT count(*) FROM ls_nodes")).scalar_one()
    if not n:
        return
    run("CREATE TEMP TABLE ls_edges (src BIGINT, dst BIGINT)")
    conn.execute(sa.text(
        "INSERT INTO ls_edges (src, dst) SELECT DISTINCT l.source_id, l.target_id FROM link_rows l"
        " WHERE l.crawl_id = :c AND l.kind = 'hyperlink' AND l.internal AND NOT l.nofollow"
        " AND l.source_id <> l.target_id AND l.source_id IN (SELECT id FROM ls_nodes)"
        " AND l.target_id IN (SELECT id FROM ls_nodes)"), params)  # fmt: skip
    run(f"CREATE INDEX {index}ls_edges_by_src ON ls_edges (src)")
    run("UPDATE ls_nodes SET outdeg = g.n FROM (SELECT src, count(*) AS n FROM ls_edges GROUP BY src) AS g"
        " WHERE ls_nodes.id = g.src")  # fmt: skip
    conn.execute(sa.text("UPDATE ls_nodes SET score = :s"), {"s": 1 / n})
    run("CREATE TEMP TABLE ls_in (id BIGINT PRIMARY KEY, inflow DOUBLE PRECISION)")
    for _ in range(ITERATIONS):
        dangling = conn.execute(sa.text("SELECT coalesce(sum(score), 0) FROM ls_nodes WHERE outdeg = 0")).scalar_one()
        run("DELETE FROM ls_in")
        run("INSERT INTO ls_in (id, inflow) SELECT e.dst, sum(s.score / s.outdeg) FROM ls_edges e"
            " JOIN ls_nodes s ON s.id = e.src GROUP BY e.dst")  # fmt: skip
        base = (1 - DAMPING) / n + DAMPING * dangling / n
        conn.execute(sa.text(
            "UPDATE ls_nodes SET score = :base + :d * coalesce((SELECT inflow FROM ls_in WHERE ls_in.id = ls_nodes.id), 0)"),
            {"base": base, "d": DAMPING})  # fmt: skip
    _scale(conn, crawl_id)
    for table in ("ls_nodes", "ls_edges", "ls_in"):
        run(f"DROP TABLE {temp}.{table}")


def _scale(conn: sa.Connection, crawl_id: int) -> None:
    """Scores to 1–100 on a log scale, written to the pages a batch at a time (ls_in is reused for the values)."""
    low, high = conn.execute(sa.text("SELECT min(score), max(score) FROM ls_nodes")).one()
    span = math.log(high) - math.log(low) if high > low else 0.0
    conn.exec_driver_sql("DELETE FROM ls_in")
    select = sa.text("SELECT id, score FROM ls_nodes WHERE id > :after ORDER BY id LIMIT :limit")
    insert = sa.text("INSERT INTO ls_in (id, inflow) VALUES (:id, :v)")
    after = -1
    while batch := conn.execute(select, {"after": after, "limit": _BATCH}).all():
        after = batch[-1][0]
        values = [{"id": i, "v": round(1 + 99 * (math.log(s) - math.log(low)) / span) if span else 100}
                  for i, s in batch]  # fmt: skip
        conn.execute(insert, values)
    conn.execute(
        sa.text("UPDATE pages SET link_score = CAST(s.v AS INTEGER) FROM (SELECT u.url, i.inflow AS v FROM ls_in i"
                " JOIN urls u ON u.id = i.id) AS s WHERE pages.crawl_id = :c AND pages.url = s.url"),
        {"c": crawl_id},
    )  # fmt: skip
