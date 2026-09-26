"""pages.rendered: SEO data taken from the browser-rendered DOM (crawl.render = "always")

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("pages") as batch:
        batch.add_column(sa.Column("rendered", sa.Boolean))


def downgrade() -> None:
    with op.batch_alter_table("pages") as batch:
        batch.drop_column("rendered")
