"""exports and reports: link path type, meta keywords

Revision ID: 0026
Revises: 0025
"""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None

BEFORE = (
    "l.kind, l.internal, l.anchor, l.alt, l.rel, l.nofollow, l.alt_attr, l.sized, l.fragment, l.hreflang, "
    "CASE WHEN l.kind = 'hyperlink' THEN coalesce(l.position, 'content') END AS position, l.path"
)
PATH_TYPE = (
    "CASE l.path_type WHEN 'a' THEN 'absolute' WHEN 'p' THEN 'protocol-relative' WHEN 'r' THEN 'root-relative'"
    " WHEN 'l' THEN 'relative' END AS path_type"
)
VIEW = (
    "CREATE VIEW links AS SELECT l.crawl_id, s.url AS source, t.url AS target, {columns} "
    "FROM link_rows l JOIN urls s ON s.id = l.source_id JOIN urls t ON t.id = l.target_id"
)


def upgrade() -> None:
    op.add_column("link_rows", sa.Column("path_type", sa.String))
    op.add_column("pages", sa.Column("meta_keywords", sa.String))
    op.add_column("pages", sa.Column("meta_keywords_count", sa.Integer))
    op.execute("DROP VIEW links")
    op.execute(VIEW.format(columns=f"{BEFORE}, {PATH_TYPE}"))


def downgrade() -> None:
    op.execute("DROP VIEW links")
    op.execute(VIEW.format(columns=BEFORE))
    op.drop_column("pages", "meta_keywords_count")
    op.drop_column("pages", "meta_keywords")
    op.drop_column("link_rows", "path_type")
