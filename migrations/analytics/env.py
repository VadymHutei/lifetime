from alembic import context
from lifetime.analytics.schema import metadata

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("Use lifetime analytics migrate CLI with a configured engine")
context.configure(connection=connection, target_metadata=metadata)
with context.begin_transaction():
    context.run_migrations()
