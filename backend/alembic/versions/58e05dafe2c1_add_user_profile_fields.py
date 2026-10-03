"""add user profile fields (phone, state, location)

Revision ID: 58e05dafe2c1
Revises: c6342965f907
Create Date: 2026-09-25 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '58e05dafe2c1'
down_revision: Union[str, None] = 'c6342965f907'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NOTE: autogenerate also detects 'spatial_ref_sys' as "removed" — that's a
    # PostGIS system table outside our ORM metadata, not something this migration
    # owns. Intentionally left alone; do not let autogenerate drop it.
    op.add_column('users', sa.Column('phone', sa.String(length=20), nullable=True))
    op.add_column('users', sa.Column('state', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('location', sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'location')
    op.drop_column('users', 'state')
    op.drop_column('users', 'phone')
