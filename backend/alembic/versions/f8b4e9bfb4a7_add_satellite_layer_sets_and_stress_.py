"""add satellite_layer_sets and stress_zones tables

Revision ID: f8b4e9bfb4a7
Revises: 4a2566747914
Create Date: 2026-09-26 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'f8b4e9bfb4a7'
down_revision: Union[str, None] = '4a2566747914'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOTE: autogenerate also detects 'spatial_ref_sys' as "removed" -- that's a
    # PostGIS system table outside our ORM metadata, not something this migration
    # owns. Intentionally left alone; do not let autogenerate drop it.
    op.create_table(
        'satellite_layer_sets',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('farm_id', sa.Uuid(), nullable=False),
        sa.Column('image_date', sa.Date(), nullable=False),
        sa.Column('true_color_tile_url', sa.String(length=1000), nullable=False),
        sa.Column('ndvi_tile_url', sa.String(length=1000), nullable=False),
        sa.Column('ndwi_tile_url', sa.String(length=1000), nullable=False),
        sa.Column('evi_tile_url', sa.String(length=1000), nullable=False),
        sa.Column('stress_tile_url', sa.String(length=1000), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['farm_id'], ['farms.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('farm_id', 'image_date', name='uq_satellite_layer_sets_farm_date'),
    )
    op.create_index(
        op.f('ix_satellite_layer_sets_farm_id'), 'satellite_layer_sets', ['farm_id'], unique=False
    )

    op.create_table(
        'stress_zones',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('farm_id', sa.Uuid(), nullable=False),
        sa.Column('image_date', sa.Date(), nullable=False),
        sa.Column('zone_type', sa.String(length=30), nullable=False),
        sa.Column('area_ha', sa.Float(), nullable=False),
        sa.Column('geometry_geojson', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('suggested_action', sa.String(length=500), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['farm_id'], ['farms.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_stress_zones_farm_id'), 'stress_zones', ['farm_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_stress_zones_farm_id'), table_name='stress_zones')
    op.drop_table('stress_zones')
    op.drop_index(op.f('ix_satellite_layer_sets_farm_id'), table_name='satellite_layer_sets')
    op.drop_table('satellite_layer_sets')
