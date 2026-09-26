"""sitemaps: the files a crawl read and their URL entries

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sitemap_files",
        sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String, nullable=False),
        sa.Column("kind", sa.String),
        sa.Column("bytes", sa.Integer),
        sa.Column("urls", sa.Integer),
        sa.Column("sitemaps", sa.Integer),
        sa.Column("error", sa.String),
    )
    op.create_table(
        "sitemap_urls",
        sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String, nullable=False),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("lastmod", sa.String),
    )
    op.create_index("sitemap_urls_by_url", "sitemap_urls", ["crawl_id", "url"])


def downgrade() -> None:
    op.drop_table("sitemap_urls")
    op.drop_table("sitemap_files")
