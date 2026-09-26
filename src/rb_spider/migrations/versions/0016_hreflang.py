"""hreflang: the code on link rows, elements outside <head> per page

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

COLUMNS = "l.kind, l.internal, l.anchor, l.alt, l.rel, l.nofollow, l.alt_attr, l.sized, l.fragment"
VIEW = (
    "CREATE VIEW links AS SELECT l.crawl_id, s.url AS source, t.url AS target, {columns} "
    "FROM link_rows l JOIN urls s ON s.id = l.source_id JOIN urls t ON t.id = l.target_id"
)


def upgrade() -> None:
    op.add_column("link_rows", sa.Column("hreflang", sa.String))
    op.add_column("pages", sa.Column("hreflang_outside_head", sa.Integer))
    for name, column in (("by_source", "source_id"), ("by_target", "target_id")):
        op.create_index(f"link_rows_hreflang_{name}", "link_rows", ["crawl_id", column],
                        sqlite_where=sa.text("kind = 'hreflang'"))  # fmt: skip
    op.execute("DROP VIEW links")
    op.execute(VIEW.format(columns=f"{COLUMNS}, l.hreflang"))


def downgrade() -> None:
    op.execute("DROP VIEW links")
    op.execute(VIEW.format(columns=COLUMNS))
    op.drop_index("link_rows_hreflang_by_source", "link_rows")
    op.drop_index("link_rows_hreflang_by_target", "link_rows")
    op.drop_column("pages", "hreflang_outside_head")
    op.drop_column("link_rows", "hreflang")
