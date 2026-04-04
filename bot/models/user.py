from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base

if TYPE_CHECKING:
    from bot.models.immunity import Immunity
    from bot.models.infection import Infection
    from bot.models.resource import ResourceTransaction
    from bot.models.virus import Virus


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("bio_coins >= 0", name="ck_users_bio_coins_non_negative"),
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

    def __repr__(self) -> str:
        return f"<User tg_id={self.tg_id} username={self.username!r}>"
