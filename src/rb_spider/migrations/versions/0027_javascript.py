"""javascript: raw vs rendered columns, link origin, render events, old AJAX scheme

Revision ID: 0027
Revises: 0026
"""

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

BEFORE = (
    "l.kind, l.internal, l.anchor, l.alt, l.rel, l.nofollow, l.alt_attr, l.sized, l.fragment, l.hreflang, "
    "CASE WHEN l.kind = 'hyperlink' THEN coalesce(l.position, 'content') END AS position, l.path, "
    "CASE l.path_type WHEN 'a' THEN 'absolute' WHEN 'p' THEN 'protocol-relative' WHEN 'r' THEN 'root-relative'"
    " WHEN 'l' THEN 'relative' END AS path_type"
)
# stored only for a rendered page's links: every other hyperlink came from the HTML
ORIGIN = (
    "CASE WHEN l.kind = 'hyperlink' THEN CASE l.origin WHEN 'r' THEN 'rendered' WHEN 'b' THEN 'html & rendered'"
    " ELSE 'html' END END AS origin"
)
VIEW = (
    "CREATE VIEW links AS SELECT l.crawl_id, s.url AS source, t.url AS target, {columns} "
    "FROM link_rows l JOIN urls s ON s.id = l.source_id JOIN urls t ON t.id = l.target_id"
)
PAGE_COLUMNS = [
    ("raw_title", sa.String),
    ("raw_meta_description", sa.String),
    ("raw_h1", sa.String),
    ("raw_canonical", sa.String),
    ("raw_directives", sa.String),
    ("raw_word_count", sa.Integer),
    ("js_outlinks", sa.Integer),
    ("js_errors", sa.Integer),
    ("js_warnings", sa.Integer),
    ("blocked_resources", sa.Integer),
    ("ajax_meta_fragment", sa.Boolean),
    ("hashbang_links", sa.Integer),
]


def upgrade() -> None:
    op.add_column("link_rows", sa.Column("origin", sa.String))
    for name, kind in PAGE_COLUMNS:
        op.add_column("pages", sa.Column(name, kind))
    op.execute("DROP VIEW links")
    op.execute(VIEW.format(columns=f"{BEFORE}, {ORIGIN}"))
    op.create_table(
        "render_events",
        sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String, nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("message", sa.String),
        sa.Column("resource", sa.String),
    )
    op.create_index("render_events_by_url", "render_events", ["crawl_id", "url"])


def downgrade() -> None:
    op.drop_index("render_events_by_url", "render_events")
    op.drop_table("render_events")
    op.execute("DROP VIEW links")
    op.execute(VIEW.format(columns=BEFORE))
    for name, _ in reversed(PAGE_COLUMNS):
        op.drop_column("pages", name)
    op.drop_column("link_rows", "origin")
