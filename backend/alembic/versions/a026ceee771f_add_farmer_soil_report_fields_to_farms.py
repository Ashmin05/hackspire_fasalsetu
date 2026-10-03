"""add farmer soil report fields to farms

Revision ID: a026ceee771f
Revises: 9831a24d76b5
Create Date: 2026-09-28 03:04:36.444154

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a026ceee771f'
down_revision: Union[str, None] = '9831a24d76b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOTE: autogenerate also detected 'spatial_ref_sys' as "removed" — that's a
    # PostGIS system table outside our ORM metadata, not something this migration
    # owns. Intentionally left alone; do not let autogenerate drop it.
    # server_default backfills existing rows as "no report" then is dropped,
    # matching the ORM's Python-side default=False for new rows going forward.
    op.add_column('farms', sa.Column('has_soil_report', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.alter_column('farms', 'has_soil_report', server_default=None)
    op.add_column('farms', sa.Column('soil_report_ph', sa.Float(), nullable=True))
    op.add_column('farms', sa.Column('soil_report_nitrogen', sa.String(length=10), nullable=True))
    op.add_column('farms', sa.Column('soil_report_phosphorus', sa.String(length=10), nullable=True))
    op.add_column('farms', sa.Column('soil_report_potassium', sa.String(length=10), nullable=True))
    op.add_column('farms', sa.Column('soil_report_organic_matter_pct', sa.Float(), nullable=True))
    op.add_column('farms', sa.Column('soil_report_recorded_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('farms', 'soil_report_recorded_at')
    op.drop_column('farms', 'soil_report_organic_matter_pct')
    op.drop_column('farms', 'soil_report_potassium')
    op.drop_column('farms', 'soil_report_phosphorus')
    op.drop_column('farms', 'soil_report_nitrogen')
    op.drop_column('farms', 'soil_report_ph')
    op.drop_column('farms', 'has_soil_report')
