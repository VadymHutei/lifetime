"""Analytics schema shared by the repository and its Alembic revision."""

from sqlalchemy import (
    JSON,
    Column,
    Float,
    Index,
    Integer,
    MetaData,
    String,
    Table,
)

metadata = MetaData()
events = Table(
    "request_events",
    metadata,
    Column("event_id", String(64), primary_key=True),
    Column("edge_request_id", String(64), unique=True),
    Column("timestamp", String(32), nullable=False),
    Column("source", String(12), nullable=False),
    Column("method", String(16), nullable=False),
    Column("path", String(256), nullable=False),
    Column("route", String(256)),
    Column("endpoint", String(100)),
    Column("query", JSON, nullable=False),
    Column("status", Integer, nullable=False),
    Column("duration_ms", Float, nullable=False),
    Column("response_bytes", Integer),
    Column("address_token", String(64)),
    Column("address_key_id", String(12)),
    Column("address_family", Integer),
    Column("raw_ip", String(45)),
    Column("user_agent", String(120), nullable=False),
    Column("referer", String(256)),
    Column("locale", String(2)),
    Column("dataset_id", String(100)),
    Column("app_version", String(50), nullable=False),
    Column("validity", String(24), nullable=False),
    Column("client_class", String(24), nullable=False),
    Column("security_class", String(24), nullable=False),
    Column("outcome", String(24), nullable=False),
    Column("reasons", JSON, nullable=False),
    Column("ruleset_version", String(24), nullable=False),
    Column("confidence", Float, nullable=False),
    Column("flags", JSON, nullable=False),
)
Index("ix_events_timestamp", events.c.timestamp)
Index("ix_events_status_time", events.c.status, events.c.timestamp)
Index("ix_events_validity_time", events.c.validity, events.c.timestamp)
Index("ix_events_client_time", events.c.client_class, events.c.timestamp)
Index("ix_events_security_time", events.c.security_class, events.c.timestamp)
Index("ix_events_address_time", events.c.address_token, events.c.timestamp)

daily = Table(
    "daily_request_counts",
    metadata,
    Column("day", String(10), primary_key=True),
    Column("validity", String(24), primary_key=True),
    Column("client_class", String(24), primary_key=True),
    Column("security_class", String(24), primary_key=True),
    Column("outcome", String(24), primary_key=True),
    Column("count", Integer, nullable=False),
)
