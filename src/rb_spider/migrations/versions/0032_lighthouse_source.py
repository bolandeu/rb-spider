"""lighthouse audits: the source (local Lighthouse or PageSpeed Insights)

Revision ID: 0032
Revises: 0031
"""

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lighthouse_audits", sa.Column("source", sa.String))


def downgrade() -> None:
    with op.batch_alter_table("lighthouse_audits") as batch:
        batch.drop_column("source")
