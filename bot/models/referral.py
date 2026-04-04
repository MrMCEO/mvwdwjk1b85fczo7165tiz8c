"""Referral program models."""

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class Referral(Base):
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.tg_id", ondelete="CASCADE"),
        index=True,
    )
    referred_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.tg_id", ondelete="CASCADE"),
        unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    is_qualified: Mapped[bool] = mapped_column(Boolean, default=False)
    last_active: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ReferralReward(Base):
    __tablename__ = "referral_rewards"
    __table_args__ = (
        UniqueConstraint("user_id", "level", name="uq_referral_rewards_user_level"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.tg_id", ondelete="CASCADE"),
        index=True,
    )
    level: Mapped[int] = mapped_column(Integer, nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
