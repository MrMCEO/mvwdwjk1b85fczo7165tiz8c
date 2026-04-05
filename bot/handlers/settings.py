"""
Settings handlers — управление настройками уведомлений.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.settings import settings_kb
from bot.models.user import User

router = Router(name="settings")

# Допустимые типы уведомлений и их метки для текста
_NOTIFY_LABELS: dict[str, str] = {
    "attacks": "⚔️ Атаки",
    "infections": "🦠 Заражения",
    "cooldowns": "⏱ Кулдауны",
    "events": "🌍 Ивенты",
}


async def _get_user(session: AsyncSession, tg_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    return result.scalar_one_or_none()


def _settings_text(user: User) -> str:
    return (
        "⚙️ <b>Настройки уведомлений</b>\n\n"
        f"⚔️ <b>Атаки</b>: {'✅ Вкл' if user.notify_attacks else '❌ Выкл'}\n"
        f"<i>Уведомления о входящих и исходящих атаках.</i>\n\n"
        f"🦠 <b>Заражения</b>: {'✅ Вкл' if user.notify_infections else '❌ Выкл'}\n"
        f"<i>Уведомления о новых заражениях твоего вируса.</i>\n\n"
        f"⏱ <b>Кулдауны</b>: {'✅ Вкл' if user.notify_cooldowns else '❌ Выкл'}\n"
        f"<i>Уведомления об окончании перезарядки.</i>\n\n"
        f"🌍 <b>Ивенты</b>: {'✅ Вкл' if user.notify_events else '❌ Выкл'}\n"
        f"<i>Уведомления о глобальных игровых событиях.</i>\n"
    )


@router.callback_query(F.data == "settings_menu")
async def cb_settings(callback: CallbackQuery, session: AsyncSession) -> None:
    """Показать меню настроек уведомлений."""
    user = await _get_user(session, callback.from_user.id)
    if user is None:
        await callback.answer("Игрок не найден. Используй /start.", show_alert=True)
        return

    await callback.message.edit_text(
        _settings_text(user),
        reply_markup=settings_kb(user),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("toggle_notify_"))
async def cb_toggle_notify(callback: CallbackQuery, session: AsyncSession) -> None:
    """Переключить настройку уведомления и обновить сообщение."""
    notify_type = callback.data[len("toggle_notify_"):]  # "attacks" / "infections" / ...

    if notify_type not in _NOTIFY_LABELS:
        await callback.answer("Неизвестный тип уведомления.", show_alert=True)
        return

    user = await _get_user(session, callback.from_user.id)
    if user is None:
        await callback.answer("Игрок не найден.", show_alert=True)
        return

    field = f"notify_{notify_type}"
    current = bool(getattr(user, field))
    setattr(user, field, not current)
    await session.flush()

    label = _NOTIFY_LABELS[notify_type]
    new_state = "включены" if not current else "выключены"
    await callback.answer(f"{label}: {new_state}")

    await callback.message.edit_text(
        _settings_text(user),
        reply_markup=settings_kb(user),
        parse_mode="HTML",
    )
