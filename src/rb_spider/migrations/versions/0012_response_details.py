"""pages: response time, Last-Modified and the response headers of every URL

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None

COLUMNS = [("response_ms", sa.Integer), ("last_modified", sa.String), ("headers", sa.String)]


def upgrade() -> None:
    with op.batch_alter_table("pages") as batch:
        for name, kind in COLUMNS:
            batch.add_column(sa.Column(name, kind))


def downgrade() -> None:
    with op.batch_alter_table("pages") as batch:
        for name, _ in reversed(COLUMNS):
            batch.drop_column(name)
