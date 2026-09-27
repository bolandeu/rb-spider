"""lighthouse audits

Revision ID: 0031
Revises: 0030
"""

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lighthouse_audits",
        sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String, nullable=False),
        sa.Column("strategy", sa.String, nullable=False),
        sa.Column("audit", sa.String, nullable=False),
        sa.Column("score", sa.Float),
        sa.Column("value", sa.Float),
        sa.Column("display", sa.String),
        sa.Column("items", sa.String),
    )
    op.create_index("lighthouse_audits_by_url", "lighthouse_audits", ["crawl_id", "url"])


def downgrade() -> None:
    op.drop_index("lighthouse_audits_by_url", "lighthouse_audits")
    op.drop_table("lighthouse_audits")
