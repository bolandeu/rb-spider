"""rendered page screenshots

Revision ID: 0030
Revises: 0029
"""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pages", sa.Column("screenshot", sa.String))


def downgrade() -> None:
    op.drop_column("pages", "screenshot")
