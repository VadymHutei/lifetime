"""Use 64-bit counters on MySQL; SQLite INTEGER is already signed 64-bit."""

from alembic import op
import sqlalchemy as sa

revision = "analytics_0003"
down_revision = "analytics_0002"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "mysql":
        op.alter_column(
            "request_events",
            "response_bytes",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=True,
        )
        op.alter_column(
            "daily_request_counts",
            "count",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=False,
        )


def downgrade():
    # Keep the expanded storage type. Narrowing could truncate valid events;
    # old versions read BIGINT values through ordinary Python integers.
    pass
