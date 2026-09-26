"""pages: no-response / robots / refresh fields; issues table

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("pages") as batch:
        batch.add_column(sa.Column("error", sa.String))  # why there is no response (status_code 0)
        batch.add_column(sa.Column("blocked", sa.String))  # "robots_txt": not fetched on purpose
        batch.add_column(sa.Column("refresh_url", sa.String))  # target of a meta / HTTP Refresh
        batch.add_column(sa.Column("refresh_kind", sa.String))  # "meta" | "http"
    op.create_table(
        "issues",
        sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String, nullable=False),
        sa.Column("url", sa.String, nullable=False),
        sa.Column("detail", sa.String),
    )
    op.create_index("issues_by_code", "issues", ["crawl_id", "code"])


def downgrade() -> None:
    op.drop_index("issues_by_code", "issues")
    op.drop_table("issues")
    with op.batch_alter_table("pages") as batch:
        for column in ("refresh_kind", "refresh_url", "blocked", "error"):
            batch.drop_column(column)
