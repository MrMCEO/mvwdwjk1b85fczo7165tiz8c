"""Suggestion and SuggestBlock models."""
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class SuggestionStatus(enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class Suggestion(Base):
    __tablename__ = "suggestions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[SuggestionStatus] = mapped_column(
        Enum(
            SuggestionStatus,
            name="suggestionstatus",
            values_callable=lambda x: [e.value for e in x],
        ),
        default=SuggestionStatus.PENDING,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now(), index=True
    )
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    moderated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    def __repr__(self) -> str:
        return f"<Suggestion id={self.id} user={self.user_id} status={self.status.value}>"


class SuggestBlock(Base):
    __tablename__ = "suggest_blocks"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    blocked_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now()
    )
    blocked_by: Mapped[int] = mapped_column(BigInteger, nullable=False)

    def __repr__(self) -> str:
        return f"<SuggestBlock user={self.user_id} by={self.blocked_by}>"
