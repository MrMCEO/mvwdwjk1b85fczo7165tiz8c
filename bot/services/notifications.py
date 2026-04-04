"""
Notifications service — helpers for checking per-user notification preferences.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.user import User


async def should_notify(session: AsyncSession, user_id: int, notify_type: str) -> bool:
    """
    Проверить, включён ли данный тип уведомлений для пользователя.

    notify_type — одно из: "attacks", "infections", "cooldowns", "events".
    Возвращает True, если нужно отправить уведомление.
    """
    result = await session.execute(select(User).where(User.tg_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return False
    return bool(getattr(user, f"notify_{notify_type}", True))
