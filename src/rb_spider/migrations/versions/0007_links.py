"""links table; pages: external / parsed flags and outlink counts

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

COLUMNS = [
    ("external", sa.Boolean),
    ("parsed", sa.Boolean),
    ("internal_outlinks", sa.Integer),
    ("external_outlinks", sa.Integer),
    ("internal_nofollow_outlinks", sa.Integer),
    ("uncrawlable_outlinks", sa.Integer),
]


def upgrade() -> None:
    with op.batch_alter_table("pages") as batch:
        for name, kind in COLUMNS:
            batch.add_column(sa.Column(name, kind))
    op.create_table(
        "links",
        sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("target", sa.String, nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("internal", sa.Boolean, nullable=False),
        sa.Column("anchor", sa.String),
        sa.Column("alt", sa.String),
        sa.Column("rel", sa.String),
        sa.Column("nofollow", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("links_by_source", "links", ["crawl_id", "source"])
    op.create_index("links_by_target", "links", ["crawl_id", "target"])


def downgrade() -> None:
    op.drop_index("links_by_target", "links")
    op.drop_index("links_by_source", "links")
    op.drop_table("links")
    with op.batch_alter_table("pages") as batch:
        for name, _ in reversed(COLUMNS):
            batch.drop_column(name)
