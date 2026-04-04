"""add display_name to users

Добавляет поле display_name в таблицу users.
Кастомное отображаемое имя (до 20 символов), доступно всем игрокам.
None = показывается @username как раньше.

Revision ID: b1c2d3e4f5a6
Revises: 3acd5884d7b3
Create Date: 2026-04-04 22:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "3acd5884d7b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "display_name",
                sa.String(length=20),
                nullable=True,
                default=None,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("display_name")
