import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base

if TYPE_CHECKING:
    from bot.models.user import User


class Currency(enum.Enum):
    BIO_COINS = "BIO_COINS"
    PREMIUM_COINS = "PREMIUM_COINS"


class TransactionReason(enum.Enum):
    MINING = "MINING"
    INFECTION_INCOME = "INFECTION_INCOME"
    INFECTION_LOSS = "INFECTION_LOSS"
    UPGRADE = "UPGRADE"
    DONATION = "DONATION"
    DAILY_BONUS = "DAILY_BONUS"


class ResourceTransaction(Base):
    __tablename__ = "resource_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), index=True
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[Currency] = mapped_column(Enum(Currency), nullable=False)
    reason: Mapped[TransactionReason] = mapped_column(Enum(TransactionReason), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now()
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="transactions")

    def __repr__(self) -> str:
        return (
            f"<ResourceTransaction id={self.id} user={self.user_id}"
            f" amount={self.amount} currency={self.currency} reason={self.reason}>"
        )
