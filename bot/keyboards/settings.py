"""Клавиатура настроек уведомлений."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.models.user import User


def settings_kb(user: User) -> InlineKeyboardMarkup:
    """Кнопки-тогглы для каждого типа уведомлений."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"⚔️ Атаки {'✅' if user.notify_attacks else '❌'}",
        callback_data="toggle_notify_attacks",
    )
    builder.button(
        text=f"🦠 Заражения {'✅' if user.notify_infections else '❌'}",
        callback_data="toggle_notify_infections",
    )
    builder.button(
        text=f"⏱ Кулдауны {'✅' if user.notify_cooldowns else '❌'}",
        callback_data="toggle_notify_cooldowns",
    )
    builder.button(
        text=f"🌍 Ивенты {'✅' if user.notify_events else '❌'}",
        callback_data="toggle_notify_events",
    )
    builder.button(text="◀️ Назад", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()
