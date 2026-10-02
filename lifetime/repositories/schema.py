"""Reference tables. Schema changes are applied only by Alembic."""

from sqlalchemy import (
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()
dataset_versions = Table(
    "dataset_versions",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("imported_at", String(32), nullable=False),
    Column("common_year", Integer, nullable=False),
    Column("source_release_date", String(10), nullable=False),
    Column("retrieved_at", String(40), nullable=False),
    Column("metadata_json", Text, nullable=False),
    Column("manifest_json", Text, nullable=False),
)
active_reference = Table(
    "active_reference",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("dataset_id", String(64), ForeignKey("dataset_versions.id"), nullable=False),
    CheckConstraint("id = 1"),
)
locations = Table(
    "locations",
    metadata,
    Column("dataset_id", String(64), ForeignKey("dataset_versions.id"), primary_key=True),
    Column("code", String(3), primary_key=True),
    Column("slug", String(160), nullable=False),
    Column("name", String(200), nullable=False),
    Column("entity_type", String(16), nullable=False),
    Column("aggregate_type", String(32)),
    Column("public", Integer, nullable=False),
    Column("metadata_json", Text, nullable=False),
    UniqueConstraint("dataset_id", "slug"),
    CheckConstraint("entity_type IN ('country','territory','area','aggregate')"),
    CheckConstraint("public IN (0,1)"),
)
life_expectancy = Table(
    "life_expectancy",
    metadata,
    Column("dataset_id", String(64), primary_key=True),
    Column("location_code", String(3), primary_key=True),
    Column("year", Integer, primary_key=True),
    Column("sex", String(8), primary_key=True),
    Column("indicator", String(40), primary_key=True),
    Column("value_years", Float),
    Column("status", String(16), nullable=False),
    Column("missing_reason", String(100)),
    Column("metadata_json", Text, nullable=False),
    ForeignKeyConstraint(["dataset_id", "location_code"], ["locations.dataset_id", "locations.code"]),
    CheckConstraint("sex IN ('total','female','male')"),
    CheckConstraint("value_years IS NULL OR (value_years > 0 AND value_years < 130)"),
    CheckConstraint(
        "(status = 'available' AND value_years IS NOT NULL AND missing_reason IS NULL) OR (status = 'missing' AND value_years IS NULL AND missing_reason IS NOT NULL)"
    ),
)
legacy_aliases = Table(
    "legacy_aliases",
    metadata,
    Column("dataset_id", String(64), ForeignKey("dataset_versions.id"), primary_key=True),
    Column("legacy_id", Integer, primary_key=True),
    Column("legacy_alias", String(160), nullable=False),
    Column("target_code", String(3)),
    Column("metadata_json", Text, nullable=False),
    UniqueConstraint("dataset_id", "legacy_alias"),
    ForeignKeyConstraint(["dataset_id", "target_code"], ["locations.dataset_id", "locations.code"]),
)
