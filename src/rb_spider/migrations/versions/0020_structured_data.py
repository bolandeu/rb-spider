"""structured data: per-page summary of JSON-LD / Microdata / RDFa and their validation

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

COLUMNS = [
    ("sd_formats", sa.String),
    ("sd_types", sa.String),
    ("sd_parse_errors", sa.Integer),
    ("sd_errors", sa.Integer),
    ("sd_warnings", sa.Integer),
    ("sd_rich_errors", sa.Integer),
    ("sd_rich_warnings", sa.Integer),
    ("sd_messages", sa.String),
    ("sd_features", sa.String),
]


def upgrade() -> None:
    for name, kind in COLUMNS:
        op.add_column("pages", sa.Column(name, kind))


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column("pages", name)
