"""add_unique_constraint_referral_rewards_user_level

Adds a unique constraint on (user_id, level) in referral_rewards to prevent
double-claiming of the same reward level in concurrent requests.

Revision ID: 418564fc3521
Revises: b4b089b720b9
Create Date: 2026-04-04 21:45:39.675545

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '418564fc3521'
down_revision: Union[str, None] = 'b4b089b720b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("referral_rewards") as batch_op:
        batch_op.create_unique_constraint(
            "uq_referral_rewards_user_level",
            ["user_id", "level"],
        )


def downgrade() -> None:
    with op.batch_alter_table("referral_rewards") as batch_op:
        batch_op.drop_constraint("uq_referral_rewards_user_level", type_="unique")
