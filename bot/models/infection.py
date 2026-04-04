from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base

if TYPE_CHECKING:
    from bot.models.user import User


class Infection(Base):
    __tablename__ = "infections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    attacker_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), index=True
    )
    victim_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), index=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now()
    )
    damage_per_tick: Mapped[float] = mapped_column(Float, default=1.0, server_default="1.0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")

    # Relationships
    attacker: Mapped["User"] = relationship(
        "User", foreign_keys=[attacker_id], back_populates="infections_sent"
    )
    victim: Mapped["User"] = relationship(
        "User", foreign_keys=[victim_id], back_populates="infections_received"
    )

    def __repr__(self) -> str:
        return (
            f"<Infection id={self.id} attacker={self.attacker_id}"
            f" victim={self.victim_id} active={self.is_active}>"
        )
