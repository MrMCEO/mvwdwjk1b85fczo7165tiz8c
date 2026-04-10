"""Model for storing bot event logs in the database."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class BotLog(Base):
    __tablename__ = "bot_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now(), index=True
    )
    level: Mapped[str] = mapped_column(String(10), default="INFO")
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    message: Mapped[str] = mapped_column(Text, default="")
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    def __repr__(self) -> str:
        return f"<BotLog id={self.id} type={self.event_type} user={self.user_id}>"
