"""URL checks: link fragments, page bookmark fingerprints, per-URL check flags

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

COLUMNS = "l.kind, l.internal, l.anchor, l.alt, l.rel, l.nofollow, l.alt_attr, l.sized"
VIEW = (
    "CREATE VIEW links AS SELECT l.crawl_id, s.url AS source, t.url AS target, {columns} "
    "FROM link_rows l JOIN urls s ON s.id = l.source_id JOIN urls t ON t.id = l.target_id"
)


def upgrade() -> None:
    op.add_column("link_rows", sa.Column("fragment", sa.String))
    op.create_index("link_rows_with_fragment", "link_rows", ["crawl_id"], sqlite_where=sa.text("fragment IS NOT NULL"))
    op.add_column("pages", sa.Column("anchor_ids", sa.String))
    op.add_column("pages", sa.Column("url_issues", sa.String))
    op.execute("DROP VIEW links")
    op.execute(VIEW.format(columns=f"{COLUMNS}, l.fragment"))


def downgrade() -> None:
    op.execute("DROP VIEW links")
    op.execute(VIEW.format(columns=COLUMNS))
    op.drop_index("link_rows_with_fragment", "link_rows")
    op.drop_column("pages", "url_issues")
    op.drop_column("pages", "anchor_ids")
    op.drop_column("link_rows", "fragment")
