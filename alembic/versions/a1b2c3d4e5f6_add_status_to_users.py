"""add_status_to_users

Adds the `status` column to the users table to support the 5-level status
system: FREE | BIO_PLUS | BIO_PRO | BIO_ELITE | BIO_LEGEND.

Revision ID: a1b2c3d4e5f6
Revises: 2cdb2038bbd2
Create Date: 2026-04-04 18:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "2cdb2038bbd2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "status",
                sa.String(length=20),
                server_default="FREE",
                nullable=False,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("status")
