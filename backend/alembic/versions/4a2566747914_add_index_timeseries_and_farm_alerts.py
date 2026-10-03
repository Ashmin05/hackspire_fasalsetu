"""add index_timeseries and farm_alerts tables

Revision ID: 4a2566747914
Revises: 49d07458618e
Create Date: 2026-09-26 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4a2566747914'
down_revision: Union[str, None] = '49d07458618e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOTE: autogenerate also detects 'spatial_ref_sys' as "removed" -- that's a
    # PostGIS system table outside our ORM metadata, not something this migration
    # owns. Intentionally left alone; do not let autogenerate drop it.
    op.create_table(
        'index_timeseries',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('farm_id', sa.Uuid(), nullable=False),
        sa.Column('image_date', sa.Date(), nullable=False),
        sa.Column('satellite', sa.String(length=10), nullable=False),
        sa.Column('cloud_pct', sa.Float(), nullable=False),
        sa.Column('ndvi_mean', sa.Float(), nullable=False),
        sa.Column('ndwi_mean', sa.Float(), nullable=False),
        sa.Column('evi_mean', sa.Float(), nullable=False),
        sa.Column('benchmark_ndvi', sa.Float(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['farm_id'], ['farms.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('farm_id', 'image_date', name='uq_index_timeseries_farm_date'),
    )
    op.create_index(
        op.f('ix_index_timeseries_farm_id'), 'index_timeseries', ['farm_id'], unique=False
    )

    op.create_table(
        'farm_alerts',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('farm_id', sa.Uuid(), nullable=False),
        sa.Column('alert_type', sa.String(length=30), nullable=False),
        sa.Column('severity', sa.String(length=20), nullable=False),
        sa.Column('message', sa.String(length=500), nullable=False),
        sa.Column('detected_at', sa.Date(), nullable=False),
        sa.Column('is_read', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['farm_id'], ['farms.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_farm_alerts_farm_id'), 'farm_alerts', ['farm_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_farm_alerts_farm_id'), table_name='farm_alerts')
    op.drop_table('farm_alerts')
    op.drop_index(op.f('ix_index_timeseries_farm_id'), table_name='index_timeseries')
    op.drop_table('index_timeseries')
