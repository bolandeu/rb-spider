"""security: missing headers, sniffed content type, forms and unsafe links per page

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

COLUMNS = [
    ("security_missing", sa.String),
    ("sniffed_type", sa.String),
    ("forms", sa.Integer),
    ("unsafe_blank_links", sa.Integer),
    ("protocol_relative", sa.Integer),
]


def upgrade() -> None:
    for name, kind in COLUMNS:
        op.add_column("pages", sa.Column(name, kind))


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column("pages", name)
