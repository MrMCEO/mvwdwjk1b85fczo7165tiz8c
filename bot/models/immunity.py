import enum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Enum, Float, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base

if TYPE_CHECKING:
    from bot.models.user import User


class ImmunityBranch(enum.Enum):
    BARRIER = "BARRIER"
    DETECTION = "DETECTION"
    REGENERATION = "REGENERATION"


class Immunity(Base):
    __tablename__ = "immunities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), unique=True, index=True
    )
    level: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    resistance: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    detection_power: Mapped[float] = mapped_column(Float, default=0.1, server_default="0.1")
    recovery_speed: Mapped[float] = mapped_column(Float, default=0.03, server_default="0.03")  # balanced: was 0.1, too high base auto-cure

    # Relationships
    owner: Mapped["User"] = relationship("User", back_populates="immunity", lazy="selectin")
    upgrades: Mapped[list["ImmunityUpgrade"]] = relationship(
        "ImmunityUpgrade", back_populates="immunity", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Immunity id={self.id} level={self.level} resistance={self.resistance}>"


class ImmunityUpgrade(Base):
    __tablename__ = "immunity_upgrades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    immunity_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("immunities.id", ondelete="CASCADE"), index=True
    )
    branch: Mapped[ImmunityBranch] = mapped_column(Enum(ImmunityBranch), nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    effect_value: Mapped[float] = mapped_column(Float, default=0.0, server_default="0.0")

    # Relationships
    immunity: Mapped["Immunity"] = relationship("Immunity", back_populates="upgrades", lazy="selectin")

    def __repr__(self) -> str:
        return f"<ImmunityUpgrade id={self.id} branch={self.branch} level={self.level}>"
