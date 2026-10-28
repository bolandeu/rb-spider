"""spider_fetches: the page storage of `spider fetch` (ADR 0001), in schema `cache` on PostgreSQL

Expand only: a new table nobody else reads — the previous release does not know it and keeps working.

Revision ID: 0036
Revises: 0035
"""

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None

# On SQLite the engine maps the schema away (core/db.py: schema_translate_map)
SCHEMA = "cache"
ID = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "spider_fetches",
        sa.Column("id", ID, primary_key=True),
        sa.Column("url", sa.String, nullable=False),
        sa.Column("url_key", sa.String, nullable=False),
        sa.Column("domain_key", sa.String),
        sa.Column("rendered", sa.Boolean, nullable=False),
        sa.Column("final_url", sa.String, nullable=False),
        sa.Column("status", sa.Integer, nullable=False),
        sa.Column("content_hash", sa.String, nullable=False),
        sa.Column("cache_key", sa.String, nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bytes", sa.Integer, nullable=False),
        sa.PrimaryKeyConstraint("id", name="spider_fetches_pk"),
        sa.UniqueConstraint("url_key", "rendered", name="spider_fetches_url_key_rendered_uq"),
        schema=SCHEMA,
    )
    op.create_index("spider_fetches_by_cache_key", "spider_fetches", ["cache_key"], unique=True, schema=SCHEMA)
    op.create_index("spider_fetches_by_fetched_at", "spider_fetches", ["fetched_at"], schema=SCHEMA)


def downgrade() -> None:
    op.drop_table("spider_fetches", schema=SCHEMA)
