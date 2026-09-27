"""link score

Revision ID: 0029
Revises: 0028
"""

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pages", sa.Column("link_score", sa.Integer))


def downgrade() -> None:
    op.drop_column("pages", "link_score")
