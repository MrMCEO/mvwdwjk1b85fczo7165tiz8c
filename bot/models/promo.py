"""Promo code models — PromoCode and PromoActivation."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)
    bio_coins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    premium_coins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_activations: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    current_activations: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")

    def __repr__(self) -> str:
        return (
            f"<PromoCode id={self.id} code={self.code!r}"
            f" bio={self.bio_coins} premium={self.premium_coins}>"
        )


class PromoActivation(Base):
    __tablename__ = "promo_activations"

    __table_args__ = (
        UniqueConstraint("promo_id", "user_id", name="uq_promo_user"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    promo_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("promo_codes.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), index=True
    )
    activated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    def __repr__(self) -> str:
        return (
            f"<PromoActivation promo_id={self.promo_id}"
            f" user_id={self.user_id}>"
        )
