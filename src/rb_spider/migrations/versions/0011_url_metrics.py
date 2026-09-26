"""url_metrics: metrics enrichers (plugins) add to a crawl's URLs

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "url_metrics",
        sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("url", sa.String, primary_key=True),
        sa.Column("source", sa.String, primary_key=True),
        sa.Column("name", sa.String, primary_key=True),
        sa.Column("value", sa.Float),
        sa.Column("text", sa.String),
    )


def downgrade() -> None:
    op.drop_table("url_metrics")
