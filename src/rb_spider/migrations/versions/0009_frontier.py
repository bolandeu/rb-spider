"""frontier: every URL handed to the crawl queue (resume); crawls.pid of the process running it

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "frontier",
        sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("url", sa.String, primary_key=True),
        sa.Column("depth", sa.Integer, nullable=False),
        sa.Column("check_only", sa.Boolean, nullable=False),
        sa.Column("done", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("frontier_pending", "frontier", ["crawl_id", "done"])
    with op.batch_alter_table("crawls") as batch:
        batch.add_column(sa.Column("pid", sa.Integer))


def downgrade() -> None:
    with op.batch_alter_table("crawls") as batch:
        batch.drop_column("pid")
    op.drop_index("frontier_pending", "frontier")
    op.drop_table("frontier")
