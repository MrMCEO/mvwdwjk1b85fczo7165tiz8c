"""Event model — server-wide temporary events (epidemics, gold rushes, etc.)."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base


class EventType(enum.Enum):
    PANDEMIC = "PANDEMIC"               # Босс-вирус: все должны защищаться
    GOLD_RUSH = "GOLD_RUSH"             # x2 добыча ресурсов
    ARMS_RACE = "ARMS_RACE"             # -50% стоимость прокачки
    PLAGUE_SEASON = "PLAGUE_SEASON"     # +50% шанс заражения для всех
    IMMUNITY_WAVE = "IMMUNITY_WAVE"     # +50% к защите для всех
    MUTATION_STORM = "MUTATION_STORM"   # x3 шанс мутаций
    CEASEFIRE = "CEASEFIRE"             # Никто не может атаковать


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[EventType] = mapped_column(Enum(EventType), nullable=False)
    title: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(String(512), default="", server_default="")
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now()
    )
    ends_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )  # admin tg_id; no FK to allow system events

    # Relationships
    pandemic_participants: Mapped[list[PandemicParticipant]] = relationship(
        "PandemicParticipant",
        back_populates="event",
        cascade="all, delete-orphan",
    )
    event_participants: Mapped[list[EventParticipant]] = relationship(
        "EventParticipant",
        back_populates="event",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<Event id={self.id} type={self.event_type.value}"
            f" active={self.is_active}>"
        )


class PandemicParticipant(Base):
    """Tracks players who participate in a PANDEMIC boss fight."""

    __tablename__ = "pandemic_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("events.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.tg_id", ondelete="CASCADE"),
    )
    damage_dealt: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_attack_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), server_default=func.now()
    )

    # Relationships
    event: Mapped[Event] = relationship("Event", back_populates="pandemic_participants")

    def __repr__(self) -> str:
        return (
            f"<PandemicParticipant event={self.event_id}"
            f" user={self.user_id} dmg={self.damage_dealt}>"
        )


class EventParticipant(Base):
    """Tracks player activity scores in non-PANDEMIC events (for top-5 prizes)."""

    __tablename__ = "event_participants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("events.id", ondelete="CASCADE"),
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.tg_id", ondelete="CASCADE"),
    )
    # +1 per activity: mine, attack, upgrade
    activity_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    __table_args__ = (
        UniqueConstraint("event_id", "user_id", name="uq_event_participant"),
    )

    # Relationships
    event: Mapped[Event] = relationship("Event", back_populates="event_participants")

    def __repr__(self) -> str:
        return (
            f"<EventParticipant event={self.event_id}"
            f" user={self.user_id} score={self.activity_score}>"
        )
