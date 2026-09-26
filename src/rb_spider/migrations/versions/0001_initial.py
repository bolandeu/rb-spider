"""projects, crawls, pages

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.String, nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "crawls",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("project_id", sa.Integer, sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_url", sa.String, nullable=False),
        sa.Column("status", sa.String, nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("pages", sa.Integer, nullable=False, server_default="0"),
    )
    op.create_table(
        "pages",
        sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("url", sa.String, primary_key=True),
        sa.Column("status_code", sa.Integer, nullable=False),
        sa.Column("redirect_url", sa.String),
        sa.Column("content_type", sa.String),
        sa.Column("title", sa.String),
        sa.Column("bytes", sa.Integer, nullable=False),
        sa.Column("depth", sa.Integer, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("pages")
    op.drop_table("crawls")
    op.drop_table("projects")
