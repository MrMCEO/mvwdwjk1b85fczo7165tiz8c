"""Alliance and AllianceMember models — clan/guild system for BioWars."""

from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, Enum, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base

if TYPE_CHECKING:
    from bot.models.user import User


class AllianceRole(enum.Enum):
    LEADER = "LEADER"    # Лидер (создатель)
    OFFICER = "OFFICER"  # Офицер (может приглашать/кикать)
    MEMBER = "MEMBER"    # Участник


class AlliancePrivacy(enum.Enum):
    CLOSED = "CLOSED"    # 🔒 только приглашения
    REQUEST = "REQUEST"  # 📩 по запросу (вступление через заявку)
    OPEN = "OPEN"        # 🔓 открытый (вступление без одобрения)


class JoinRequestStatus(enum.Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


# Human-readable labels with emoji
ROLE_LABELS: dict[AllianceRole, str] = {
    AllianceRole.LEADER: "👑 Лидер",
    AllianceRole.OFFICER: "⚔️ Офицер",
    AllianceRole.MEMBER: "👤 Участник",
}

PRIVACY_LABELS: dict[AlliancePrivacy, str] = {
    AlliancePrivacy.CLOSED: "🔒 Закрытый",
    AlliancePrivacy.REQUEST: "📩 По запросу",
    AlliancePrivacy.OPEN: "🔓 Открытый",
}


class Alliance(Base):
    __tablename__ = "alliances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    tag: Mapped[str] = mapped_column(String(5), unique=True, nullable=False)
    leader_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.tg_id"), nullable=False
    )
    description: Mapped[str] = mapped_column(String(256), default="", server_default="")
    # max_members is now derived: 20 + capacity_level * 5
    # The field is kept for legacy compatibility but superseded by get_alliance_max_members()
    max_members: Mapped[int] = mapped_column(Integer, default=20, server_default="20")
    defense_bonus: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Alliance upgrade currency
    alliance_coins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Treasury: bio_coins donated by members, converted to alliance_coins in bulk
    treasury_bio: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Privacy mode: OPEN / REQUEST / CLOSED
    privacy: Mapped[str] = mapped_column(String(10), default="REQUEST", server_default="REQUEST")

    # Upgrade levels
    shield_level: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    morale_level: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    capacity_level: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    mining_level: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    regen_level: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    members: Mapped[list[AllianceMember]] = relationship(
        back_populates="alliance", cascade="all, delete-orphan", lazy="selectin"
    )
    join_requests: Mapped[list[AllianceJoinRequest]] = relationship(
        back_populates="alliance", cascade="all, delete-orphan", lazy="selectin"
    )
    leader: Mapped[User] = relationship("User", foreign_keys=[leader_id], lazy="selectin")

    def __repr__(self) -> str:
        return f"<Alliance id={self.id} name={self.name!r} tag={self.tag!r}>"


class AllianceMember(Base):
    __tablename__ = "alliance_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alliance_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("alliances.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), unique=True, index=True
    )
    role: Mapped[AllianceRole] = mapped_column(
        Enum(AllianceRole), default=AllianceRole.MEMBER
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    alliance: Mapped[Alliance] = relationship(back_populates="members", lazy="selectin")
    user: Mapped[User] = relationship("User", lazy="selectin")

    def __repr__(self) -> str:
        return (
            f"<AllianceMember alliance_id={self.alliance_id} "
            f"user_id={self.user_id} role={self.role}>"
        )


class AllianceJoinRequest(Base):
    """Pending/processed join requests for REQUEST-mode alliances."""

    __tablename__ = "alliance_join_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alliance_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("alliances.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    status: Mapped[JoinRequestStatus] = mapped_column(
        Enum(JoinRequestStatus), default=JoinRequestStatus.PENDING
    )

    alliance: Mapped[Alliance] = relationship(back_populates="join_requests", lazy="selectin")
    user: Mapped[User] = relationship("User", lazy="selectin")

    def __repr__(self) -> str:
        return (
            f"<AllianceJoinRequest id={self.id} alliance_id={self.alliance_id} "
            f"user_id={self.user_id} status={self.status}>"
        )
