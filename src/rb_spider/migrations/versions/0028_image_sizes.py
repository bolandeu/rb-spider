"""images: real size, sizes as rendered, CSS background images

Revision ID: 0028
Revises: 0027
"""

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None

BEFORE = (
    "l.kind, l.internal, l.anchor, l.alt, l.rel, l.nofollow, l.alt_attr, l.sized, l.fragment, l.hreflang, "
    "CASE WHEN l.kind = 'hyperlink' THEN coalesce(l.position, 'content') END AS position, l.path, "
    "CASE l.path_type WHEN 'a' THEN 'absolute' WHEN 'p' THEN 'protocol-relative' WHEN 'r' THEN 'root-relative'"
    " WHEN 'l' THEN 'relative' END AS path_type, "
)
ORIGIN_BEFORE = (
    "CASE WHEN l.kind = 'hyperlink' THEN CASE l.origin WHEN 'r' THEN 'rendered' WHEN 'b' THEN 'html & rendered'"
    " ELSE 'html' END END AS origin"
)
# images: a CSS background (inline style or computed after rendering) is told apart from <img>
ORIGIN = (
    "CASE WHEN l.kind = 'hyperlink' THEN CASE l.origin WHEN 'r' THEN 'rendered' WHEN 'b' THEN 'html & rendered'"
    " ELSE 'html' END WHEN l.kind = 'image' AND l.origin = 'c' THEN 'css background' END AS origin"
)
VIEW = (
    "CREATE VIEW links AS SELECT l.crawl_id, s.url AS source, t.url AS target, {columns} "
    "FROM link_rows l JOIN urls s ON s.id = l.source_id JOIN urls t ON t.id = l.target_id"
)


def upgrade() -> None:
    op.add_column("pages", sa.Column("image_width", sa.Integer))
    op.add_column("pages", sa.Column("image_height", sa.Integer))
    op.execute("DROP VIEW links")
    op.execute(VIEW.format(columns=BEFORE + ORIGIN))
    op.create_table(
        "rendered_images",
        sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String, nullable=False),
        sa.Column("image", sa.String, nullable=False),
        sa.Column("real_width", sa.Integer),
        sa.Column("real_height", sa.Integer),
        sa.Column("display_width", sa.Integer),
        sa.Column("display_height", sa.Integer),
    )
    op.create_index("rendered_images_by_url", "rendered_images", ["crawl_id", "url"])


def downgrade() -> None:
    op.drop_index("rendered_images_by_url", "rendered_images")
    op.drop_table("rendered_images")
    op.execute("DROP VIEW links")
    op.execute(VIEW.format(columns=BEFORE + ORIGIN_BEFORE))
    op.drop_column("pages", "image_height")
    op.drop_column("pages", "image_width")
