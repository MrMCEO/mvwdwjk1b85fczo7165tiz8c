"""add_market_listings

Revision ID: 36c9e5fe6c65
Revises: 6a3a077c0b01
Create Date: 2026-04-04 15:58:56.295448

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "36c9e5fe6c65"
down_revision: Union[str, None] = "6a3a077c0b01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_listings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("seller_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "listing_type",
            sa.Enum("SELL_COINS", "BUY_COINS", "HIT_CONTRACT", name="listingtype"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum("ACTIVE", "COMPLETED", "CANCELLED", "EXPIRED", name="listingstatus"),
            nullable=False,
            server_default="ACTIVE",
        ),
        sa.Column("amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("price", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("target_username", sa.String(length=64), nullable=True),
        sa.Column("target_id", sa.BigInteger(), nullable=True),
        sa.Column("reward", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("buyer_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["buyer_id"], ["users.tg_id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["seller_id"], ["users.tg_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_market_listings_seller_id"), "market_listings", ["seller_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_market_listings_seller_id"), table_name="market_listings")
    op.drop_table("market_listings")
