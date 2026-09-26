"""pages: inlinks, unique inlinks and unique outlinks, computed after the crawl

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None

COLUMNS = ["inlinks", "unique_inlinks", "unique_outlinks"]


def upgrade() -> None:
    with op.batch_alter_table("pages") as batch:
        for name in COLUMNS:
            batch.add_column(sa.Column(name, sa.Integer))


def downgrade() -> None:
    with op.batch_alter_table("pages") as batch:
        for name in reversed(COLUMNS):
            batch.drop_column(name)
