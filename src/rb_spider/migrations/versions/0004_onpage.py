"""pages: title, meta description, h1, h2 details

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

COLUMNS = [
    ("title_count", sa.Integer),
    ("title_outside_head", sa.Integer),
    ("meta_description", sa.String),
    ("meta_description_count", sa.Integer),
    ("meta_description_outside_head", sa.Integer),
    ("h1", sa.String),
    ("h1_count", sa.Integer),
    ("h1_from_alt", sa.Boolean),
    ("h1_first_heading", sa.Boolean),
    ("h2", sa.String),
    ("h2_count", sa.Integer),
    ("h2_sequential", sa.Boolean),
]


def upgrade() -> None:
    with op.batch_alter_table("pages") as batch:
        for name, kind in COLUMNS:
            batch.add_column(sa.Column(name, kind))


def downgrade() -> None:
    with op.batch_alter_table("pages") as batch:
        for name, _ in reversed(COLUMNS):
            batch.drop_column(name)
