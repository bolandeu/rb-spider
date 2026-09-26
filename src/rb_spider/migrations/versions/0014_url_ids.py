"""links by URL id: `urls` + `link_rows`; `links` becomes a view with the URLs as text

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

DATA = "kind, internal, anchor, alt, rel, nofollow, alt_attr, sized"
VIEW = (
    "CREATE VIEW links AS SELECT l.crawl_id, s.url AS source, t.url AS target, "
    "l.kind, l.internal, l.anchor, l.alt, l.rel, l.nofollow, l.alt_attr, l.sized "
    "FROM link_rows l JOIN urls s ON s.id = l.source_id JOIN urls t ON t.id = l.target_id"
)


def upgrade() -> None:
    op.create_table(
        "urls",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.String, nullable=False),
        sa.UniqueConstraint("url", "crawl_id", name="urls_by_url"),
    )
    op.create_table(
        "link_rows",
        sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.Integer, nullable=False),
        sa.Column("target_id", sa.Integer, nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("internal", sa.Boolean, nullable=False),
        sa.Column("anchor", sa.String),
        sa.Column("alt", sa.String),
        sa.Column("rel", sa.String),
        sa.Column("nofollow", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("alt_attr", sa.Boolean),
        sa.Column("sized", sa.Boolean),
    )
    op.execute(
        "INSERT OR IGNORE INTO urls (url, crawl_id) SELECT source, crawl_id FROM links"
        " UNION SELECT target, crawl_id FROM links"
    )
    op.execute(
        f"INSERT INTO link_rows (crawl_id, source_id, target_id, {DATA}) SELECT l.crawl_id, s.id, t.id, {DATA.replace('kind', 'l.kind')}"  # noqa: S608
        " FROM links l JOIN urls s ON s.url = l.source AND s.crawl_id = l.crawl_id"
        " JOIN urls t ON t.url = l.target AND t.crawl_id = l.crawl_id"
    )
    op.create_index("link_rows_by_source", "link_rows", ["crawl_id", "source_id"])
    op.create_index("link_rows_by_target", "link_rows", ["crawl_id", "target_id"])
    op.drop_index("links_by_source", "links")
    op.drop_index("links_by_target", "links")
    op.drop_table("links")
    op.execute(VIEW)


def downgrade() -> None:
    op.execute("DROP VIEW links")
    op.create_table(
        "links",
        sa.Column("crawl_id", sa.Integer, sa.ForeignKey("crawls.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String, nullable=False),
        sa.Column("target", sa.String, nullable=False),
        sa.Column("kind", sa.String, nullable=False),
        sa.Column("internal", sa.Boolean, nullable=False),
        sa.Column("anchor", sa.String),
        sa.Column("alt", sa.String),
        sa.Column("rel", sa.String),
        sa.Column("nofollow", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("alt_attr", sa.Boolean),
        sa.Column("sized", sa.Boolean),
    )
    op.execute(
        f"INSERT INTO links (crawl_id, source, target, {DATA}) SELECT l.crawl_id, s.url, t.url, {DATA.replace('kind', 'l.kind')}"  # noqa: S608
        " FROM link_rows l JOIN urls s ON s.id = l.source_id JOIN urls t ON t.id = l.target_id"
    )
    op.create_index("links_by_source", "links", ["crawl_id", "source"])
    op.create_index("links_by_target", "links", ["crawl_id", "target"])
    op.drop_table("link_rows")
    op.drop_table("urls")
