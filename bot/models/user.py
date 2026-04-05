from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base

if TYPE_CHECKING:
    from bot.models.immunity import Immunity
    from bot.models.infection import Infection
    from bot.models.item import Item
    from bot.models.mutation import Mutation
    from bot.models.resource import ResourceTransaction
    from bot.models.virus import Virus


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # bio_coins can go negative (debt mechanic) — only premium_coins is non-negative
        CheckConstraint("premium_coins >= 0", name="ck_users_premium_coins_non_negative"),
    )

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, index=True)
    username: Mapped[str] = mapped_column(String(64), default="", server_default="")
    bio_coins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    premium_coins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now()
    )
    last_active: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now(), onupdate=func.now()
    )
    premium_until: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None
    )
    premium_prefix: Mapped[str | None] = mapped_column(
        String(30), nullable=True, default=None
    )  # До 5 видимых символов; String(30) — запас для HTML-escape (&amp; и т.д.)
    status: Mapped[str] = mapped_column(
        String(20), default="FREE", server_default="FREE"
    )  # UserStatus enum value, e.g. "FREE", "BIO_PLUS", …, "BIO_LEGEND"
    display_name: Mapped[str | None] = mapped_column(
        String(120), nullable=True, default=None
    )  # Кастомное отображаемое имя (до 20 символов видимых; String(120) — запас для HTML-escape)

    # Notification preferences
    notify_attacks: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    notify_infections: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    notify_cooldowns: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    notify_events: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")

    # Repeatable referral reward counter (how many times the infinite level has been claimed)
    repeatable_referral_claims: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )

    # Relationships
    virus: Mapped["Virus"] = relationship(
        "Virus", back_populates="owner", uselist=False, cascade="all, delete-orphan"
    )
    immunity: Mapped["Immunity"] = relationship(
        "Immunity", back_populates="owner", uselist=False, cascade="all, delete-orphan"
    )
    infections_sent: Mapped[list["Infection"]] = relationship(
        "Infection",
        foreign_keys="Infection.attacker_id",
        back_populates="attacker",
        cascade="all, delete-orphan",
    )
    infections_received: Mapped[list["Infection"]] = relationship(
        "Infection",
        foreign_keys="Infection.victim_id",
        back_populates="victim",
        cascade="all, delete-orphan",
    )
    transactions: Mapped[list["ResourceTransaction"]] = relationship(
        "ResourceTransaction", back_populates="user", cascade="all, delete-orphan"
    )
    mutations: Mapped[list["Mutation"]] = relationship(
        "Mutation", back_populates="owner", cascade="all, delete-orphan"
    )
    items: Mapped[list["Item"]] = relationship(
        "Item", back_populates="owner", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User tg_id={self.tg_id} username={self.username!r}>"
