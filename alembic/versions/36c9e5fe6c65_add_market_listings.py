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
    # market_listings already created in 6a3a077c0b01_add_items_table — skip
    pass


def downgrade() -> None:
    op.drop_index(op.f("ix_market_listings_seller_id"), table_name="market_listings")
    op.drop_table("market_listings")
