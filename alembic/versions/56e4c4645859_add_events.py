"""add events

Revision ID: 56e4c4645859
Revises: 36c9e5fe6c65
Create Date: 2026-04-04 16:00:23.927808

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "56e4c4645859"
down_revision: Union[str, None] = "36c9e5fe6c65"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "event_type",
            sa.Enum(
                "PANDEMIC",
                "GOLD_RUSH",
                "ARMS_RACE",
                "PLAGUE_SEASON",
                "IMMUNITY_WAVE",
                "MUTATION_STORM",
                "CEASEFIRE",
                name="eventtype",
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=512), server_default="", nullable=False),
        sa.Column("started_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("ends_at", sa.DateTime(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "pandemic_participants",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("damage_dealt", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_attack_at", sa.DateTime(), nullable=True),
        sa.Column("joined_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.tg_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_pandemic_participants_event_id"),
        "pandemic_participants",
        ["event_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_pandemic_participants_event_id"),
        table_name="pandemic_participants",
    )
    op.drop_table("pandemic_participants")
    op.drop_table("events")
