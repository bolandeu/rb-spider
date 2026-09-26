"""serp: title and description widths in pixels

Revision ID: 0022
Revises: 0021
"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pages", sa.Column("title_px", sa.Integer))
    op.add_column("pages", sa.Column("description_px", sa.Integer))


def downgrade() -> None:
    op.drop_column("pages", "description_px")
    op.drop_column("pages", "title_px")
