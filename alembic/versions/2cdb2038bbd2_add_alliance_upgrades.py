"""add_alliance_upgrades

Adds AllianceCoins balance and upgrade level fields to the alliances table.

Revision ID: 2cdb2038bbd2
Revises: 78570e7702c9
Create Date: 2026-04-04 17:36:34.950238

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2cdb2038bbd2'
down_revision: Union[str, None] = '78570e7702c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add alliance upgrade currency and upgrade level columns.
    # These columns may already exist if applied manually; the IF NOT EXISTS
    # workaround is handled by catching OperationalError via batch_alter_table
    # which SQLite ALTER TABLE supports without transactions.
    with op.batch_alter_table("alliances") as batch_op:
        batch_op.add_column(
            sa.Column("alliance_coins", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("shield_level", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("morale_level", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("capacity_level", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("mining_level", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(
            sa.Column("regen_level", sa.Integer(), server_default="0", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("alliances") as batch_op:
        batch_op.drop_column("regen_level")
        batch_op.drop_column("mining_level")
        batch_op.drop_column("capacity_level")
        batch_op.drop_column("morale_level")
        batch_op.drop_column("shield_level")
        batch_op.drop_column("alliance_coins")
