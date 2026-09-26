"""content: readability, text ratio, MinHash signatures and near-duplicate pairs

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

COLUMNS = [("flesch", sa.Float), ("words_per_sentence", sa.Float), ("text_ratio", sa.Float), ("minhash", sa.String)]


def upgrade() -> None:
    for name, kind in COLUMNS:
        op.add_column("pages", sa.Column(name, kind))
    op.create_table(
        "near_duplicates",
        sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url_a", sa.String, nullable=False),
        sa.Column("url_b", sa.String, nullable=False),
        sa.Column("similarity", sa.Float, nullable=False),
    )
    op.create_index("near_duplicates_by_a", "near_duplicates", ["crawl_id", "url_a"])
    op.create_index("near_duplicates_by_b", "near_duplicates", ["crawl_id", "url_b"])


def downgrade() -> None:
    op.drop_table("near_duplicates")
    for name, _ in reversed(COLUMNS):
        op.drop_column("pages", name)
