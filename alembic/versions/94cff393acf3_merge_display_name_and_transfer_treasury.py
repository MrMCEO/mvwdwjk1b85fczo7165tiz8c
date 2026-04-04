"""merge_display_name_and_transfer_treasury

Revision ID: 94cff393acf3
Revises: b1c2d3e4f5a6, b9e3f1a2c4d5
Create Date: 2026-04-04 21:44:18.586521

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '94cff393acf3'
down_revision: Union[str, None] = ('b1c2d3e4f5a6', 'b9e3f1a2c4d5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
