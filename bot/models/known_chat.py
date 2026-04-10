"""KnownChat model — tracks all chats the bot has interacted with."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class KnownChat(Base):
    __tablename__ = "known_chats"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chat_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # "private", "group", "supergroup", "channel"
    title: Mapped[str] = mapped_column(String(255), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    first_seen: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now()
    )

    def __repr__(self) -> str:
        return f"<KnownChat id={self.chat_id} type={self.chat_type}>"
