"""Initial reference schema and constraints.

Revision ID: reference_0001
Revises:
"""

from alembic import op
import sqlalchemy as sa

revision = "reference_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "dataset_versions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("imported_at", sa.String(32), nullable=False),
        sa.Column("common_year", sa.Integer(), nullable=False),
        sa.Column("source_release_date", sa.String(10), nullable=False),
        sa.Column("retrieved_at", sa.String(40), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
    )
    op.create_table(
        "active_reference",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("dataset_id", sa.String(64), sa.ForeignKey("dataset_versions.id"), nullable=False),
        sa.CheckConstraint("id = 1"),
    )
    op.create_table(
        "locations",
        sa.Column("dataset_id", sa.String(64), sa.ForeignKey("dataset_versions.id"), primary_key=True),
        sa.Column("code", sa.String(3), primary_key=True),
        sa.Column("slug", sa.String(160), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("entity_type", sa.String(16), nullable=False),
        sa.Column("aggregate_type", sa.String(32)),
        sa.Column("public", sa.Integer(), nullable=False),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("dataset_id", "slug"),
        sa.CheckConstraint("entity_type IN ('country','territory','area','aggregate')"),
        sa.CheckConstraint("public IN (0,1)"),
    )
    op.create_index("ix_locations_type", "locations", ["dataset_id", "entity_type"])
    op.create_table(
        "life_expectancy",
        sa.Column("dataset_id", sa.String(64), primary_key=True),
        sa.Column("location_code", sa.String(3), primary_key=True),
        sa.Column("year", sa.Integer(), primary_key=True),
        sa.Column("sex", sa.String(8), primary_key=True),
        sa.Column("indicator", sa.String(40), primary_key=True),
        sa.Column("value_years", sa.Float()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("missing_reason", sa.String(100)),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["dataset_id", "location_code"], ["locations.dataset_id", "locations.code"]),
        sa.CheckConstraint("sex IN ('total','female','male')"),
        sa.CheckConstraint("value_years IS NULL OR (value_years > 0 AND value_years < 130)"),
        sa.CheckConstraint(
            "(status = 'available' AND value_years IS NOT NULL AND missing_reason IS NULL) OR (status = 'missing' AND value_years IS NULL AND missing_reason IS NOT NULL)"
        ),
    )
    op.create_index("ix_expectancy_year", "life_expectancy", ["dataset_id", "year"])
    op.create_table(
        "legacy_aliases",
        sa.Column("dataset_id", sa.String(64), sa.ForeignKey("dataset_versions.id"), primary_key=True),
        sa.Column("legacy_id", sa.Integer(), primary_key=True),
        sa.Column("legacy_alias", sa.String(160), nullable=False),
        sa.Column("target_code", sa.String(3)),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.UniqueConstraint("dataset_id", "legacy_alias"),
        sa.ForeignKeyConstraint(["dataset_id", "target_code"], ["locations.dataset_id", "locations.code"]),
    )


def downgrade():
    for table in ("legacy_aliases", "life_expectancy", "locations", "active_reference", "dataset_versions"):
        op.drop_table(table)
