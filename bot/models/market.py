"""Market listing models — black market for P2P trading and hit contracts."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base

if TYPE_CHECKING:
    from bot.models.user import User


class ListingType(enum.Enum):
    SELL_COINS = "SELL_COINS"      # Продажа bio_coins за premium_coins
    BUY_COINS = "BUY_COINS"        # Покупка bio_coins за premium_coins
    HIT_CONTRACT = "HIT_CONTRACT"  # Контракт: заразить указанного игрока за награду


class ListingStatus(enum.Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class MarketListing(Base):
    __tablename__ = "market_listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), index=True
    )
    listing_type: Mapped[ListingType] = mapped_column(Enum(ListingType), nullable=False)
    status: Mapped[ListingStatus] = mapped_column(
        Enum(ListingStatus), default=ListingStatus.ACTIVE, server_default="ACTIVE"
    )

    # Для SELL/BUY_COINS:
    amount: Mapped[int] = mapped_column(Integer, default=0, server_default="0")   # сколько bio_coins
    price: Mapped[int] = mapped_column(Integer, default=0, server_default="0")    # цена в premium_coins

    # Для HIT_CONTRACT:
    target_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reward: Mapped[int] = mapped_column(Integer, default=0, server_default="0")   # награда за выполнение (bio_coins)

    buyer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.tg_id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    seller: Mapped[User] = relationship("User", foreign_keys=[seller_id])
    buyer: Mapped[User] = relationship("User", foreign_keys=[buyer_id])

    def __repr__(self) -> str:
        return (
            f"<MarketListing id={self.id} type={self.listing_type} "
            f"status={self.status} seller={self.seller_id}>"
        )
