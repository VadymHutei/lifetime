"""Preserve source binary64 precision in MySQL.

Revision ID: reference_0002
Revises: reference_0001
SQLite's existing FLOAT affinity already stores binary64 and remains intact.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DOUBLE

revision = "reference_0002"
down_revision = "reference_0001"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "mysql":
        op.alter_column(
            "life_expectancy",
            "value_years",
            type_=DOUBLE(asdecimal=False),
            existing_type=sa.Float(),
            existing_nullable=True,
        )


def downgrade():
    if op.get_bind().dialect.name == "mysql":
        # Keep the wider compatible numeric type. A schema downgrade must not
        # irreversibly round provider statistics; reference_0001 accepts DOUBLE.
        pass
