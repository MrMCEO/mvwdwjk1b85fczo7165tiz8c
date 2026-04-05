"""
Модель настроек репортов для администраторов чатов.
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from bot.models.base import Base


class ChatReportSettings(Base):
    """Настройки уведомлений о репортах — per-admin per-chat."""

    __tablename__ = "chat_report_settings"

    admin_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.tg_id", ondelete="CASCADE"),
        primary_key=True,
    )
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    notify_reports: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1"
    )

    def __repr__(self) -> str:
        return (
            f"<ChatReportSettings admin_id={self.admin_id} "
            f"chat_id={self.chat_id} notify={self.notify_reports}>"
        )
