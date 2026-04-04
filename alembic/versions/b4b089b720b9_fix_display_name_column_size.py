"""fix_display_name_and_prefix_column_sizes

Fixes String length for columns that store html.escape()-processed user input:
  - users.display_name: 20 → 120  (20 raw chars × max 6 for &quot; = 120)
  - users.premium_prefix: 10 → 30  (5 raw chars × max 6 for &quot; = 30)

Revision ID: b4b089b720b9
Revises: 94cff393acf3
Create Date: 2026-04-04 21:45:06.757562

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4b089b720b9'
down_revision: Union[str, None] = '94cff393acf3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite does not enforce VARCHAR length at the DB level, so no actual DDL
    # change is needed for existing SQLite DBs — the constraint is enforced in
    # Python (service layer). For other databases (PostgreSQL etc.) this
    # would require an ALTER COLUMN.  We use batch_alter_table for portability.
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "display_name",
            existing_type=sa.String(length=20),
            type_=sa.String(length=120),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "premium_prefix",
            existing_type=sa.String(length=10),
            type_=sa.String(length=30),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column(
            "display_name",
            existing_type=sa.String(length=120),
            type_=sa.String(length=20),
            existing_nullable=True,
        )
        batch_op.alter_column(
            "premium_prefix",
            existing_type=sa.String(length=30),
            type_=sa.String(length=10),
            existing_nullable=True,
        )
