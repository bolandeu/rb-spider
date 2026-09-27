"""crawl settings: the robots.txt line that blocked a URL

Revision ID: 0024
Revises: 0023
"""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pages", sa.Column("blocked_rule", sa.String))


def downgrade() -> None:
    op.drop_column("pages", "blocked_rule")
