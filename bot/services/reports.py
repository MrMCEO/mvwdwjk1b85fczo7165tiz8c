"""
Сервис для работы с репортами: настройки уведомлений администраторов.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.chat_settings import ChatReportSettings


async def should_notify_report(
    session: AsyncSession, admin_id: int, chat_id: int
) -> bool:
    """Проверить, нужно ли уведомлять администратора о репортах в данном чате.

    Если записи ещё нет — создаёт её с notify=True и возвращает True.
    """
    result = await session.execute(
        select(ChatReportSettings).where(
            ChatReportSettings.admin_id == admin_id,
            ChatReportSettings.chat_id == chat_id,
        )
    )
    settings = result.scalar_one_or_none()

    if settings is None:
        settings = ChatReportSettings(
            admin_id=admin_id, chat_id=chat_id, notify_reports=True
        )
        session.add(settings)
        await session.flush()
        return True

    return settings.notify_reports


async def toggle_report_notify(
    session: AsyncSession, admin_id: int, chat_id: int
) -> bool:
    """Переключить уведомления о репортах для администратора в конкретном чате.

    Возвращает новое значение notify_reports.
    """
    result = await session.execute(
        select(ChatReportSettings).where(
            ChatReportSettings.admin_id == admin_id,
            ChatReportSettings.chat_id == chat_id,
        )
    )
    settings = result.scalar_one_or_none()

    if settings is None:
        # Создаём запись с уже выключенными уведомлениями (инвертируем дефолт True)
        settings = ChatReportSettings(
            admin_id=admin_id, chat_id=chat_id, notify_reports=False
        )
        session.add(settings)
        await session.flush()
        return False

    settings.notify_reports = not settings.notify_reports
    await session.flush()
    return settings.notify_reports
