"""Alembic environment: migrations run on the connection handed over by core.storage.

No alembic.ini and no logging setup — the CLI owns both. `spider` applies pending
migrations itself when it opens the database.
"""

from alembic import context

from rb_spider.core.storage import metadata

connection = context.config.attributes["connection"]
context.configure(connection=connection, target_metadata=metadata, render_as_batch=True)
with context.begin_transaction():
    context.run_migrations()
