import enum
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Enum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from bot.models.base import Base

if TYPE_CHECKING:
    from bot.models.user import User


class VirusBranch(enum.Enum):
    LETHALITY = "LETHALITY"
    CONTAGION = "CONTAGION"
    STEALTH = "STEALTH"


class Virus(Base):
    __tablename__ = "viruses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("users.tg_id", ondelete="CASCADE"), unique=True, index=True
    )
    name: Mapped[str] = mapped_column(String(64), default="Неизвестный вирус", server_default="Неизвестный вирус")
    level: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    attack_power: Mapped[int] = mapped_column(Integer, default=10, server_default="10")
    spread_rate: Mapped[float] = mapped_column(Float, default=1.0, server_default="1.0")  # balanced: was 0.1, see combat.py formula
    mutation_points: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    # Relationships
    owner: Mapped["User"] = relationship("User", back_populates="virus")
    upgrades: Mapped[list["VirusUpgrade"]] = relationship(
        "VirusUpgrade", back_populates="virus", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Virus id={self.id} name={self.name!r} level={self.level}>"


class VirusUpgrade(Base):
    __tablename__ = "virus_upgrades"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    virus_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("viruses.id", ondelete="CASCADE"), index=True
    )
    branch: Mapped[VirusBranch] = mapped_column(Enum(VirusBranch), nullable=False)
    level: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    effect_value: Mapped[float] = mapped_column(Float, default=0.0, server_default="0.0")

    # Relationships
    virus: Mapped["Virus"] = relationship("Virus", back_populates="upgrades")

    def __repr__(self) -> str:
        return f"<VirusUpgrade id={self.id} branch={self.branch} level={self.level}>"
