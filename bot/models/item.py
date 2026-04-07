"""Item model — craftable one-use items stored in player inventory."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base

if TYPE_CHECKING:
    from bot.models.user import User


class ItemType(enum.Enum):
    # Защитные
    VACCINE = "VACCINE"                         # Мгновенное излечение от 1 заражения
    SHIELD_BOOST = "SHIELD_BOOST"               # +50% защиты на 2 часа
    ANTIDOTE = "ANTIDOTE"                       # Излечение от ВСЕХ заражений

    # Атакующие
    BIO_BOMB = "BIO_BOMB"                       # Гарантированная атака (100% шанс)
    VIRUS_ENHANCER = "VIRUS_ENHANCER"           # +100% урон на 1 атаку
    STEALTH_CLOAK = "STEALTH_CLOAK"             # Полная невидимость на 1 атаку

    # Экономические
    RESOURCE_BOOSTER = "RESOURCE_BOOSTER"       # x2 добыча на 3 часа
    LUCKY_CHARM = "LUCKY_CHARM"                 # x3 ежедневный бонус (одноразово)

    # Особые
    SPY_DRONE = "SPY_DRONE"                     # Показать все статы цели
    MUTATION_SERUM = "MUTATION_SERUM"           # Гарантированная случайная мутация


ITEM_CONFIG: dict[ItemType, dict] = {
    ItemType.VACCINE:          {"cost": 200,  "emoji": "💉", "name": "Вакцина",           "desc": "Мгновенное излечение от 1 заражения"},
    ItemType.SHIELD_BOOST:     {"cost": 300,  "emoji": "🛡",  "name": "Усиление щита",     "desc": "+50% защиты на 2 часа"},
    ItemType.ANTIDOTE:         {"cost": 800,  "emoji": "💊", "name": "Антидот",            "desc": "Излечение от ВСЕХ заражений"},
    ItemType.BIO_BOMB:         {"cost": 500,  "emoji": "💣", "name": "Био-бомба",          "desc": "Гарантированная атака (100% шанс)"},
    ItemType.VIRUS_ENHANCER:   {"cost": 400,  "emoji": "⚡", "name": "Усилитель вируса",   "desc": "+100% урон на 1 атаку"},
    ItemType.STEALTH_CLOAK:    {"cost": 350,  "emoji": "👻", "name": "Плащ невидимости",   "desc": "Полная скрытность на 1 атаку"},
    ItemType.RESOURCE_BOOSTER: {"cost": 250,  "emoji": "📦", "name": "Ускоритель добычи",  "desc": "x2 добыча на 3 часа"},
    ItemType.LUCKY_CHARM:      {"cost": 150,  "emoji": "🍀", "name": "Талисман удачи",     "desc": "x3 ежедневный бонус (одноразово)"},
    ItemType.SPY_DRONE:        {"cost": 300,  "emoji": "🔭", "name": "Дрон-разведчик",     "desc": "Показать все статы цели"},
    ItemType.MUTATION_SERUM:   {"cost": 600,  "emoji": "🧪", "name": "Сыворотка мутации",  "desc": "Гарантированная случайная мутация"},
}


class Item(Base):
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), index=True
    )
    item_type: Mapped[ItemType] = mapped_column(Enum(ItemType), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now()
    )
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # Для временных эффектов (SHIELD_BOOST, RESOURCE_BOOSTER):
    effect_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    owner: Mapped[User] = relationship("User", back_populates="items", lazy="selectin")

    def __repr__(self) -> str:
        return (
            f"<Item id={self.id} type={self.item_type.value}"
            f" owner={self.owner_id} used={self.is_used}>"
        )
