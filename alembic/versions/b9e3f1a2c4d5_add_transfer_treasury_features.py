"""add_transfer_treasury_features

Documents the addition of:
- TransactionReason.TRANSFER_OUT, TRANSFER_IN, ALLIANCE_DONATION
  (SQLite stores enums as VARCHAR — no DDL change needed)
- alliance_join_requests table (created in 3acd5884d7b3 if not already present)
- alliances.treasury_bio, alliances.privacy (created in 3acd5884d7b3 if not present)

All schema work is idempotent (guarded by IF NOT EXISTS / inspect).

Revision ID: b9e3f1a2c4d5
Revises: 3acd5884d7b3
Create Date: 2026-04-04 22:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision: str = "b9e3f1a2c4d5"
down_revision: Union[str, None] = "3acd5884d7b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(conn, name: str) -> bool:
    return inspect(conn).has_table(name)


def upgrade() -> None:
    """
    Ensure all schema changes introduced by the treasury/privacy/transfer feature
    are present in the DB.

    Most of these were already applied in migration 3acd5884d7b3; this migration
    handles the case where the DB might be missing them (fresh install path).
    """
    conn = op.get_bind()

    # alliance_join_requests — may already exist from 3acd5884d7b3
    if not _table_exists(conn, "alliance_join_requests"):
        op.create_table(
            "alliance_join_requests",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("alliance_id", sa.Integer(), nullable=False),
            sa.Column("user_id", sa.BigInteger(), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(),
                server_default=sa.text("(CURRENT_TIMESTAMP)"),
                nullable=False,
            ),
            sa.Column(
                "status",
                sa.String(length=20),
                server_default="PENDING",
                nullable=False,
            ),
            sa.ForeignKeyConstraint(["alliance_id"], ["alliances.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["user_id"], ["users.tg_id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            op.f("ix_alliance_join_requests_alliance_id"),
            "alliance_join_requests",
            ["alliance_id"],
            unique=False,
        )
        op.create_index(
            op.f("ix_alliance_join_requests_user_id"),
            "alliance_join_requests",
            ["user_id"],
            unique=False,
        )

    # alliances: treasury_bio, privacy columns
    alliance_cols = {col["name"] for col in inspect(conn).get_columns("alliances")}
    with op.batch_alter_table("alliances") as batch_op:
        if "treasury_bio" not in alliance_cols:
            batch_op.add_column(
                sa.Column("treasury_bio", sa.Integer(), server_default="0", nullable=False)
            )
        if "privacy" not in alliance_cols:
            batch_op.add_column(
                sa.Column(
                    "privacy", sa.String(length=10), server_default="REQUEST", nullable=False
                )
            )

    # NOTE: TransactionReason enum additions (TRANSFER_OUT, TRANSFER_IN, ALLIANCE_DONATION)
    # do not require DDL changes in SQLite — values are stored as plain VARCHAR.


def downgrade() -> None:
    # Remove alliance_join_requests if we created it here
    conn = op.get_bind()
    if _table_exists(conn, "alliance_join_requests"):
        op.drop_index(
            op.f("ix_alliance_join_requests_user_id"),
            table_name="alliance_join_requests",
        )
        op.drop_index(
            op.f("ix_alliance_join_requests_alliance_id"),
            table_name="alliance_join_requests",
        )
        op.drop_table("alliance_join_requests")

    alliance_cols = {col["name"] for col in inspect(conn).get_columns("alliances")}
    with op.batch_alter_table("alliances") as batch_op:
        if "treasury_bio" in alliance_cols:
            batch_op.drop_column("treasury_bio")
        if "privacy" in alliance_cols:
            batch_op.drop_column("privacy")
