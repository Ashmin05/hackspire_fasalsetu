"""add satellite_observations table

Revision ID: 49d07458618e
Revises: 9b61433cc742
Create Date: 2026-09-26 04:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '49d07458618e'
down_revision: Union[str, None] = '9b61433cc742'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOTE: autogenerate also detects 'spatial_ref_sys' as "removed" -- that's a
    # PostGIS system table outside our ORM metadata, not something this migration
    # owns. Intentionally left alone; do not let autogenerate drop it.
    op.create_table(
        'satellite_observations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('farm_id', sa.Uuid(), nullable=False),
        sa.Column('image_date', sa.Date(), nullable=False),
        sa.Column('satellite', sa.String(length=10), nullable=False),
        sa.Column('cloud_pct', sa.Float(), nullable=False),
        sa.Column('is_fallback', sa.Boolean(), nullable=False),
        sa.Column('ndvi_mean', sa.Float(), nullable=False),
        sa.Column('ndvi_min', sa.Float(), nullable=False),
        sa.Column('ndvi_max', sa.Float(), nullable=False),
        sa.Column('ndwi_mean', sa.Float(), nullable=False),
        sa.Column('ndwi_min', sa.Float(), nullable=False),
        sa.Column('ndwi_max', sa.Float(), nullable=False),
        sa.Column('evi_mean', sa.Float(), nullable=False),
        sa.Column('evi_min', sa.Float(), nullable=False),
        sa.Column('evi_max', sa.Float(), nullable=False),
        sa.Column('ndmi_mean', sa.Float(), nullable=False),
        sa.Column('ndmi_min', sa.Float(), nullable=False),
        sa.Column('ndmi_max', sa.Float(), nullable=False),
        sa.Column('healthy_pct', sa.Float(), nullable=False),
        sa.Column('moderate_pct', sa.Float(), nullable=False),
        sa.Column('stressed_pct', sa.Float(), nullable=False),
        sa.Column('health_score', sa.Float(), nullable=False),
        sa.Column('source', sa.String(length=100), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['farm_id'], ['farms.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_satellite_observations_farm_id'), 'satellite_observations', ['farm_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_satellite_observations_farm_id'), table_name='satellite_observations')
    op.drop_table('satellite_observations')
