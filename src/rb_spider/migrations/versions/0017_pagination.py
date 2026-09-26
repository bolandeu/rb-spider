"""pagination: the page's place in a rel next/prev series, an index over next/prev link rows

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pages", sa.Column("pagination", sa.String))
    op.create_index("link_rows_pagination", "link_rows", ["crawl_id", "source_id"],
                    sqlite_where=sa.text("kind IN ('next', 'prev')"))  # fmt: skip


def downgrade() -> None:
    op.drop_index("link_rows_pagination", "link_rows")
    op.drop_column("pages", "pagination")
