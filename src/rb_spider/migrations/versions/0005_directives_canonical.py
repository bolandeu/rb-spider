"""pages: robots directives, canonical details, indexability

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

COLUMNS = [
    ("robots_directives", sa.String),
    ("robots_outside_head", sa.Integer),
    ("canonical_url", sa.String),
    ("canonical_count", sa.Integer),
    ("canonical_conflict", sa.Boolean),
    ("canonical_outside_head", sa.Integer),
    ("canonical_invalid_attr", sa.Boolean),
    ("canonical_relative", sa.Boolean),
    ("canonical_fragment", sa.Boolean),
    ("indexable", sa.Boolean),
    ("indexability_status", sa.String),
]


def upgrade() -> None:
    with op.batch_alter_table("pages") as batch:
        for name, kind in COLUMNS:
            batch.add_column(sa.Column(name, kind))


def downgrade() -> None:
    with op.batch_alter_table("pages") as batch:
        for name, _ in reversed(COLUMNS):
            batch.drop_column(name)
