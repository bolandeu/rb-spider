"""url_key, domain_key on spider_pages and spider_urls (the shared keys of rb-keys), filled for the rows already there;
the spider_v1_pages and spider_v1_links views publish them

Expand only: two nullable columns and an index each — the previous release keeps writing (its rows get NULL keys) and
reading as before. The views get the columns at the end, nothing else changes.

Revision ID: 0035
Revises: 0034
"""

import sqlalchemy as sa
from alembic import op
from rb_keys import norm_domain, norm_url

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None

TABLES = ("spider_pages", "spider_urls")
CHUNK = 5000  # rows read and updated at a time: memory stays flat on a big base

V1_PAGES = (
    "SELECT id, crawl_id, url, status_code, redirect_url, content_type, indexable, indexability_status, title,"
    " meta_description, h1, canonical_url, robots_directives, depth, word_count, response_ms, inlinks,"
    " unique_inlinks, link_score, fetched_at, url_key, domain_key FROM spider_pages"
)
# spider_links' columns (0033) plus the target's keys, read from spider_urls directly: one join instead of two
V1_LINKS = (
    "SELECT l.crawl_id, s.url AS source, t.url AS target, l.kind, l.internal, l.anchor, l.rel, l.nofollow,"
    " CASE WHEN l.kind = 'hyperlink' THEN coalesce(l.position, 'content') END AS position,"
    " CASE WHEN l.kind = 'hyperlink' THEN CASE l.origin WHEN 'r' THEN 'rendered' WHEN 'b' THEN 'html & rendered'"
    " ELSE 'html' END WHEN l.kind = 'image' AND l.origin = 'c' THEN 'css background' END AS origin,"
    " t.url_key, t.domain_key"
    " FROM spider_link_rows l JOIN spider_urls s ON s.id = l.source_id JOIN spider_urls t ON t.id = l.target_id"
)
OLD_V1_PAGES = (
    "SELECT id, crawl_id, url, status_code, redirect_url, content_type, indexable, indexability_status, title,"
    " meta_description, h1, canonical_url, robots_directives, depth, word_count, response_ms, inlinks,"
    " unique_inlinks, link_score, fetched_at FROM spider_pages"
)
OLD_V1_LINKS = (
    "SELECT crawl_id, source, target, kind, internal, anchor, rel, nofollow, position, origin FROM spider_links"
)


def _key(normalize, url: str) -> str | None:
    try:
        return normalize(url)
    except ValueError:  # not a web URL: NULL, never ""
        return None


def _backfill(conn: sa.Connection, table: str) -> None:
    select = sa.text(f"SELECT id, url FROM {table} WHERE id > :after ORDER BY id LIMIT :n")  # noqa: S608 — fixed
    update = sa.text(f"UPDATE {table} SET url_key = :url_key, domain_key = :domain_key WHERE id = :id")  # noqa: S608
    after = 0
    while rows := conn.execute(select, {"after": after, "n": CHUNK}).all():
        conn.execute(
            update,
            [{"id": id_, "url_key": _key(norm_url, url), "domain_key": _key(norm_domain, url)} for id_, url in rows],
        )
        after = rows[-1][0]


def upgrade() -> None:
    conn = op.get_bind()
    for table in TABLES:
        op.add_column(table, sa.Column("url_key", sa.String))
        op.add_column(table, sa.Column("domain_key", sa.String))
        _backfill(conn, table)
        op.create_index(f"{table}_by_url_key", table, ["url_key"])
    for name, query in (("spider_v1_pages", V1_PAGES), ("spider_v1_links", V1_LINKS)):
        op.execute(f"DROP VIEW {name}")
        op.execute(f"CREATE VIEW {name} AS {query}")


def downgrade() -> None:
    for name, query in (("spider_v1_pages", OLD_V1_PAGES), ("spider_v1_links", OLD_V1_LINKS)):
        op.execute(f"DROP VIEW {name}")
        op.execute(f"CREATE VIEW {name} AS {query}")
    for table in TABLES:
        op.drop_index(f"{table}_by_url_key", table_name=table)
        # a plain ALTER TABLE … DROP COLUMN (SQLite >= 3.35): batch mode would rebuild the table under the views on it
        op.drop_column(table, "domain_key")
        op.drop_column(table, "url_key")
