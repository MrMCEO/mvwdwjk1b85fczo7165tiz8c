"""add event_participants table for non-PANDEMIC event leaderboards

Revision ID: c1d2e3f4a5b6
Revises: 418564fc3521
Create Date: 2026-04-04 22:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c1d2e3f4a5b6"
down_revision: Union[str, None] = "418564fc3521"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "event_participants",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("activity_score", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.tg_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "user_id", name="uq_event_participant"),
    )
    op.create_index(
        op.f("ix_event_participants_event_id"),
        "event_participants",
        ["event_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_event_participants_event_id"),
        table_name="event_participants",
    )
    op.drop_table("event_participants")
