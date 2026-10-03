"""add weather_cache table

Revision ID: 8b949da19e35
Revises: a026ceee771f
Create Date: 2026-09-28 16:30:00.476702

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = '8b949da19e35'
down_revision: Union[str, None] = 'a026ceee771f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'weather_cache',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('farm_id', sa.Uuid(), nullable=False),
        sa.Column('daily', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['farm_id'], ['farms.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_weather_cache_farm_id'), 'weather_cache', ['farm_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_weather_cache_farm_id'), table_name='weather_cache')
    op.drop_table('weather_cache')
