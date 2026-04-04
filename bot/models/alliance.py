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


# Human-readable labels with emoji
ROLE_LABELS: dict[AllianceRole, str] = {
    AllianceRole.LEADER: "👑 Лидер",
    AllianceRole.OFFICER: "⚔️ Офицер",
    AllianceRole.MEMBER: "👤 Участник",
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
    max_members: Mapped[int] = mapped_column(Integer, default=20, server_default="20")
    defense_bonus: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    members: Mapped[list[AllianceMember]] = relationship(
        back_populates="alliance", cascade="all, delete-orphan"
    )
    leader: Mapped[User] = relationship("User", foreign_keys=[leader_id])

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

    alliance: Mapped[Alliance] = relationship(back_populates="members")
    user: Mapped[User] = relationship("User")

    def __repr__(self) -> str:
        return (
            f"<AllianceMember alliance_id={self.alliance_id} "
            f"user_id={self.user_id} role={self.role}>"
        )
