"""Initial analytics schema and overlapping operator views."""

from alembic import op
import sqlalchemy as sa

revision = "analytics_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Freeze revision definitions; future repository schema changes must not
    # silently alter historical upgrades.
    op.create_table(
        "request_events",
        sa.Column("event_id", sa.String(64), primary_key=True),
        sa.Column("edge_request_id", sa.String(64), unique=True),
        sa.Column("timestamp", sa.String(32), nullable=False),
        sa.Column("source", sa.String(12), nullable=False),
        sa.Column("method", sa.String(16), nullable=False),
        sa.Column("path", sa.String(256), nullable=False),
        sa.Column("route", sa.String(256)),
        sa.Column("endpoint", sa.String(100)),
        sa.Column("query", sa.JSON(), nullable=False),
        sa.Column("status", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("response_bytes", sa.Integer()),
        sa.Column("address_token", sa.String(64)),
        sa.Column("address_family", sa.Integer()),
        sa.Column("raw_ip", sa.String(45)),
        sa.Column("user_agent", sa.String(120), nullable=False),
        sa.Column("referer", sa.String(256)),
        sa.Column("locale", sa.String(2)),
        sa.Column("dataset_id", sa.String(100)),
        sa.Column("app_version", sa.String(50), nullable=False),
        sa.Column("validity", sa.String(24), nullable=False),
        sa.Column("client_class", sa.String(24), nullable=False),
        sa.Column("security_class", sa.String(24), nullable=False),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("ruleset_version", sa.String(24), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("flags", sa.JSON(), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
    )
    for name, columns in (
        ("ix_events_timestamp", ["timestamp"]),
        ("ix_events_status_time", ["status", "timestamp"]),
        ("ix_events_validity_time", ["validity", "timestamp"]),
        ("ix_events_client_time", ["client_class", "timestamp"]),
        ("ix_events_security_time", ["security_class", "timestamp"]),
        ("ix_events_address_time", ["address_token", "timestamp"]),
    ):
        op.create_index(name, "request_events", columns)
    op.create_table(
        "daily_request_counts",
        sa.Column("day", sa.String(10), primary_key=True),
        sa.Column("validity", sa.String(24), primary_key=True),
        sa.Column("client_class", sa.String(24), primary_key=True),
        sa.Column("security_class", sa.String(24), primary_key=True),
        sa.Column("outcome", sa.String(24), primary_key=True),
        sa.Column("count", sa.Integer(), nullable=False),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
        mysql_collate="utf8mb4_bin",
    )
    views = {
        "valid_requests": "validity = 'valid'",
        "bot_requests": "client_class IN ('claimed_bot', 'verified_bot')",
        "invalid_requests": "validity = 'invalid'",
        "suspicious_requests": "security_class = 'suspicious'",
    }
    for name, predicate in views.items():
        op.execute("CREATE VIEW " + name + " AS SELECT * FROM request_events WHERE " + predicate)


def downgrade():
    for name in ("valid_requests", "bot_requests", "invalid_requests", "suspicious_requests"):
        op.execute("DROP VIEW " + name)
    op.drop_table("daily_request_counts")
    op.drop_table("request_events")
