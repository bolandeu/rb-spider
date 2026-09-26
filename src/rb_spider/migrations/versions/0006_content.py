"""pages: content hash, word count, lorem ipsum

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

COLUMNS = [("content_md5", sa.String), ("word_count", sa.Integer), ("lorem_ipsum", sa.Boolean)]


def upgrade() -> None:
    with op.batch_alter_table("pages") as batch:
        for name, kind in COLUMNS:
            batch.add_column(sa.Column(name, kind))
    op.create_index("pages_by_md5", "pages", ["crawl_id", "content_md5"])


def downgrade() -> None:
    op.drop_index("pages_by_md5", "pages")
    with op.batch_alter_table("pages") as batch:
        for name, _ in reversed(COLUMNS):
            batch.drop_column(name)
