"""add irrigation_plans and irrigation_logs tables

Revision ID: 79c227277080
Revises: 8b949da19e35
Create Date: 2026-09-28 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '79c227277080'
down_revision: Union[str, None] = '8b949da19e35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'irrigation_plans',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('farm_id', sa.Uuid(), nullable=False),
        sa.Column('crop', sa.String(length=100), nullable=False),
        sa.Column('days_since_sowing', sa.Integer(), nullable=False),
        sa.Column('kc', sa.Float(), nullable=False),
        sa.Column('kc_basis', sa.String(length=20), nullable=False),
        sa.Column('root_depth_m', sa.Float(), nullable=False),
        sa.Column('soil_texture_class', sa.String(length=30), nullable=False),
        sa.Column('soil_texture_is_default', sa.Boolean(), nullable=False),
        sa.Column('taw_mm', sa.Float(), nullable=False),
        sa.Column('raw_mm', sa.Float(), nullable=False),
        sa.Column('depletion_fraction', sa.Float(), nullable=False),
        sa.Column('depletion_mm', sa.Float(), nullable=False),
        sa.Column('is_deficit', sa.Boolean(), nullable=False),
        sa.Column('computed_through', sa.Date(), nullable=False),
        sa.Column('next_irrigation_date', sa.Date(), nullable=True),
        sa.Column('next_irrigation_depth_mm', sa.Float(), nullable=True),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['farm_id'], ['farms.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_irrigation_plans_farm_id'), 'irrigation_plans', ['farm_id'], unique=True)

    op.create_table(
        'irrigation_logs',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('farm_id', sa.Uuid(), nullable=False),
        sa.Column('log_date', sa.Date(), nullable=False),
        sa.Column('depth_mm', sa.Float(), nullable=False),
        sa.Column('note', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['farm_id'], ['farms.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_irrigation_logs_farm_id'), 'irrigation_logs', ['farm_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_irrigation_logs_farm_id'), table_name='irrigation_logs')
    op.drop_table('irrigation_logs')
    op.drop_index(op.f('ix_irrigation_plans_farm_id'), table_name='irrigation_plans')
    op.drop_table('irrigation_plans')
