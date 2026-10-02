from alembic import context
from lifetime.repositories.schema import metadata

connection = context.config.attributes["connection"]
context.configure(connection=connection, target_metadata=metadata, version_table="alembic_reference_version")
with context.begin_transaction():
    context.run_migrations()
