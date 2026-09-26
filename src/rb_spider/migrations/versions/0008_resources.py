"""links: image attributes (alt attribute present, width/height set)

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("links") as batch:
        batch.add_column(sa.Column("alt_attr", sa.Boolean))
        batch.add_column(sa.Column("sized", sa.Boolean))


def downgrade() -> None:
    with op.batch_alter_table("links") as batch:
        batch.drop_column("sized")
        batch.drop_column("alt_attr")
