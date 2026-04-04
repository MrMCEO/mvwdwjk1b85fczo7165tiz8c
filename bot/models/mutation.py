"""Mutation model — random virus mutations (buffs, debuffs, rare effects)."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, Float, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base

if TYPE_CHECKING:
    from bot.models.user import User


class MutationType(enum.Enum):
    # Баффы (положительные)
    TOXIC_SPIKE = "TOXIC_SPIKE"                   # +30% урона на 6 часов
    RAPID_SPREAD = "RAPID_SPREAD"                 # +50% заразности на 4 часа
    PHANTOM_STRAIN = "PHANTOM_STRAIN"             # +40% скрытности на 8 часов
    RESOURCE_DRAIN = "RESOURCE_DRAIN"             # +20% кражи ресурсов на 6 часов
    ADAPTIVE_SHELL = "ADAPTIVE_SHELL"             # +25% ко всей защите на 4 часа
    REGENERATIVE_CORE = "REGENERATIVE_CORE"       # +30% регенерации на 6 часов
    DOUBLE_STRIKE = "DOUBLE_STRIKE"               # Две атаки вместо одной (одноразово)
    BIO_MAGNET = "BIO_MAGNET"                     # +100% к добыче ресурсов на 2 часа

    # Дебаффы (отрицательные)
    UNSTABLE_CODE = "UNSTABLE_CODE"               # -20% атаки на 4 часа
    IMMUNE_LEAK = "IMMUNE_LEAK"                   # -15% защиты на 6 часов
    SLOW_REPLICATION = "SLOW_REPLICATION"         # -30% заразности на 4 часа

    # Редкие (очень мощные, очень редкие)
    PLAGUE_BURST = "PLAGUE_BURST"                 # Атака задевает 3 случайных игроков одновременно
    ABSOLUTE_IMMUNITY = "ABSOLUTE_IMMUNITY"       # Полная неуязвимость на 1 час
    EVOLUTION_LEAP = "EVOLUTION_LEAP"             # +1 уровень ко всем веткам вируса навсегда


class MutationRarity(enum.Enum):
    COMMON = "COMMON"           # 60% шанс (баффы слабые)
    UNCOMMON = "UNCOMMON"       # 25% шанс (баффы средние)
    RARE = "RARE"               # 12% шанс (сильные)
    LEGENDARY = "LEGENDARY"     # 3% шанс (очень мощные)


class Mutation(Base):
    __tablename__ = "mutations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), index=True
    )
    mutation_type: Mapped[MutationType] = mapped_column(Enum(MutationType), nullable=False)
    rarity: Mapped[MutationRarity] = mapped_column(Enum(MutationRarity), nullable=False)
    effect_value: Mapped[float] = mapped_column(Float, default=0.0, server_default="0.0")
    duration_hours: Mapped[float] = mapped_column(Float, default=4.0, server_default="4.0")
    activated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now()
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")

    # Relationships
    owner: Mapped[User] = relationship("User", back_populates="mutations")

    def __repr__(self) -> str:
        return (
            f"<Mutation id={self.id} type={self.mutation_type.value}"
            f" rarity={self.rarity.value} active={self.is_active}>"
        )
