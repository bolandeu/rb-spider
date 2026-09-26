"""validation and mobile: HTML structure from the source, viewport, plugins

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

COLUMNS = [
    ("head_tags", sa.Integer),
    ("body_tags", sa.Integer),
    ("body_before_html", sa.Boolean),
    ("head_not_first", sa.Boolean),
    ("invalid_head_element", sa.String),
    ("viewport", sa.String),
    ("plugins", sa.Integer),
]


def upgrade() -> None:
    for name, kind in COLUMNS:
        op.add_column("pages", sa.Column(name, kind))
    op.create_index("link_rows_mobile", "link_rows", ["crawl_id", "source_id"],
                    sqlite_where=sa.text("kind = 'mobile_alternate'"))  # fmt: skip


def downgrade() -> None:
    op.drop_index("link_rows_mobile", "link_rows")
    for name, _ in reversed(COLUMNS):
        op.drop_column("pages", name)
