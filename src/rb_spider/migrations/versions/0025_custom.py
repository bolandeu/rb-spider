"""custom search / extraction results, link position and path

Revision ID: 0025
Revises: 0024
"""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None

COLUMNS = "l.kind, l.internal, l.anchor, l.alt, l.rel, l.nofollow, l.alt_attr, l.sized, l.fragment, l.hreflang"
VIEW = (
    "CREATE VIEW links AS SELECT l.crawl_id, s.url AS source, t.url AS target, {columns} "
    "FROM link_rows l JOIN urls s ON s.id = l.source_id JOIN urls t ON t.id = l.target_id"
)


def upgrade() -> None:
    op.add_column("link_rows", sa.Column("position", sa.String))
    op.add_column("link_rows", sa.Column("path", sa.String))
    op.execute("DROP VIEW links")
    # position: stored empty for "content" (most links) — the view names it
    op.execute(
        VIEW.format(
            columns=f"{COLUMNS}, CASE WHEN l.kind = 'hyperlink' THEN coalesce(l.position, 'content')"
            " END AS position, l.path"
        )
    )
    op.create_table(
        "custom_values",
        sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String, nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("value", sa.String),
        sa.Column("n", sa.Integer, nullable=False),
    )
    op.create_index("custom_values_by_name", "custom_values", ["crawl_id", "kind", "name"])


def downgrade() -> None:
    op.drop_table("custom_values")
    op.execute("DROP VIEW links")
    op.execute(VIEW.format(columns=COLUMNS))
    op.drop_column("link_rows", "path")
    op.drop_column("link_rows", "position")
