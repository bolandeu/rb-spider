"""spider_v1_* views: what other tools, Directus and reports read instead of the tables

Their columns are a contract: a different shape is a new spider_v2_* view, v1 is dropped only after every consumer has
moved (root AGENTS.md, Service map). The tables behind them change freely.

Revision ID: 0034
Revises: 0033
"""

from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None

VIEWS = {
    "spider_v1_crawls": (
        "SELECT c.id AS crawl_id, p.name AS project, c.start_url, c.status, c.started_at, c.finished_at, c.pages"
        " FROM spider_crawls c JOIN spider_projects p ON p.id = c.project_id"
    ),
    "spider_v1_pages": (
        "SELECT id, crawl_id, url, status_code, redirect_url, content_type, indexable, indexability_status, title,"
        " meta_description, h1, canonical_url, robots_directives, depth, word_count, response_ms, inlinks,"
        " unique_inlinks, link_score, fetched_at FROM spider_pages"
    ),
    "spider_v1_issues": "SELECT id, crawl_id, code, url, detail FROM spider_issues",
    "spider_v1_links": (
        "SELECT crawl_id, source, target, kind, internal, anchor, rel, nofollow, position, origin FROM spider_links"
    ),
}


def upgrade() -> None:
    for name, query in VIEWS.items():
        op.execute(f"CREATE VIEW {name} AS {query}")


def downgrade() -> None:
    for name in VIEWS:
        op.execute(f"DROP VIEW {name}")
