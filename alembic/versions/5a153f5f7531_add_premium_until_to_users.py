"""add premium_until to users

Revision ID: 5a153f5f7531
Revises: fefb12584025
Create Date: 2026-04-04 16:48:25.071333

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5a153f5f7531'
down_revision: Union[str, None] = 'fefb12584025'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add premium_until column to users table.
    # nullable=True, default NULL — existing users have no subscription.
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("premium_until", sa.DateTime(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("premium_until")
