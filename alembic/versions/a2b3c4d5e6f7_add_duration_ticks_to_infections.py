"""add duration_ticks to infections

Revision ID: a2b3c4d5e6f7
Revises: 6e4dfdb75465
Create Date: 2026-04-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, None] = '6e4dfdb75465'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('infections', sa.Column('duration_ticks', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('infections', 'duration_ticks')
