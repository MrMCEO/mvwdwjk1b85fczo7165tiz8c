"""Market listing models — БиоБиржа for P2P trading and hit contracts."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base

if TYPE_CHECKING:
    from bot.models.item import Item
    from bot.models.mutation import Mutation
    from bot.models.user import User


class ListingType(enum.Enum):
    SELL_ITEM = "SELL_ITEM"          # Продажа предмета из лаборатории за 🧫
    SELL_MUTATION = "SELL_MUTATION"  # Продажа мутации из инвентаря за 🧫
    HIT_CONTRACT = "HIT_CONTRACT"    # Контракт: заразить указанного игрока за награду

    # Deprecated — оставлены для обратной совместимости с историческими данными в БД
    SELL_COINS = "SELL_COINS"        # Устарело: продажа bio за premium
    BUY_COINS = "BUY_COINS"         # Устарело: покупка bio за premium


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

    # Для SELL_ITEM / SELL_MUTATION: цена в bio_coins
    price: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Для SELL_ITEM:
    item_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("items.id"), nullable=True
    )

    # Для SELL_MUTATION:
    mutation_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("mutations.id"), nullable=True
    )

    # Для HIT_CONTRACT:
    target_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reward: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # награда (bio_coins)

    # Устаревшие поля (SELL_COINS / BUY_COINS) — сохранены для совместимости
    amount: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    buyer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.tg_id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    seller: Mapped[User] = relationship("User", foreign_keys=[seller_id])
    buyer: Mapped[User] = relationship("User", foreign_keys=[buyer_id])
    item: Mapped[Item | None] = relationship("Item", foreign_keys=[item_id])
    mutation: Mapped[Mutation | None] = relationship("Mutation", foreign_keys=[mutation_id])

    def __repr__(self) -> str:
        return (
            f"<MarketListing id={self.id} type={self.listing_type} "
            f"status={self.status} seller={self.seller_id}>"
        )
