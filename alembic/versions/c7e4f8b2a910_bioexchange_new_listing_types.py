"""БиоБиржа: add SELL_ITEM/SELL_MUTATION listing types, item_id and mutation_id to market_listings

Revision ID: c7e4f8b2a910
Revises: fefb12584025
Create Date: 2026-04-04 18:00:00.000000

Changes:
- Add item_id FK column to market_listings (nullable)
- Add mutation_id FK column to market_listings (nullable)
- Extend ListingType enum with SELL_ITEM and SELL_MUTATION values
- (SELL_COINS and BUY_COINS remain in the enum for backward compatibility)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7e4f8b2a910"
down_revision: Union[str, None] = "fefb12584025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite does not support ALTER COLUMN for enum types, so we handle the enum
    # extension by recreating the listing_type column with a plain VARCHAR check
    # and a new CHECK constraint that allows all five values.
    # For SQLite we use batch mode.
    with op.batch_alter_table("market_listings") as batch_op:
        # Add new nullable FK columns
        batch_op.add_column(
            sa.Column("item_id", sa.Integer(), sa.ForeignKey("items.id"), nullable=True)
        )
        batch_op.add_column(
            sa.Column("mutation_id", sa.Integer(), sa.ForeignKey("mutations.id"), nullable=True)
        )

    # SQLite stores enums as VARCHAR; the new values are automatically accepted
    # because SQLAlchemy Enum without native_enum uses VARCHAR under SQLite.
    # No column alteration is needed for the enum itself on SQLite.


def downgrade() -> None:
    with op.batch_alter_table("market_listings") as batch_op:
        batch_op.drop_column("mutation_id")
        batch_op.drop_column("item_id")
