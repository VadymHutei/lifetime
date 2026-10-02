"""Identify address HMAC key without retaining key material."""

from alembic import op
import sqlalchemy as sa

revision = "analytics_0002"
down_revision = "analytics_0001"
branch_labels = None
depends_on = None


def upgrade():
    # Development builds briefly created this column in 0001. Both forms are
    # accepted; existing request events and tokens are preserved.
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("request_events")}
    if "address_key_id" not in columns:
        op.add_column("request_events", sa.Column("address_key_id", sa.String(12), nullable=True))


def downgrade():
    with op.batch_alter_table("request_events") as batch:
        batch.drop_column("address_key_id")
