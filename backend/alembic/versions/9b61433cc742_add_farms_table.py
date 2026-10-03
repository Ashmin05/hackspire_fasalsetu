"""add farms table

Revision ID: 9b61433cc742
Revises: 58e05dafe2c1
Create Date: 2026-09-25 21:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '9b61433cc742'
down_revision: Union[str, None] = '58e05dafe2c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOTE: autogenerate also detects 'spatial_ref_sys' as "removed" — that's a
    # PostGIS system table outside our ORM metadata, not something this migration
    # owns. Intentionally left alone; do not let autogenerate drop it.
    op.create_table(
        'farms',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('crop', sa.String(length=100), nullable=False),
        sa.Column('variety', sa.String(length=100), nullable=True),
        sa.Column('sowing_date', sa.Date(), nullable=False),
        sa.Column('irrigation_method', sa.String(length=100), nullable=True),
        sa.Column('polygon_geojson', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('area_ha', sa.Float(), nullable=False),
        sa.Column('centroid_lat', sa.Float(), nullable=False),
        sa.Column('centroid_lng', sa.Float(), nullable=False),
        sa.Column('state', sa.String(length=100), nullable=True),
        sa.Column('district', sa.String(length=100), nullable=True),
        sa.Column('address', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_farms_user_id'), 'farms', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_farms_user_id'), table_name='farms')
    op.drop_table('farms')
