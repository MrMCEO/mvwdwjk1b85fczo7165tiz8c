"""Клавиатура настроек уведомлений."""

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.models.user import User


def _toggle_style(enabled: bool) -> ButtonStyle:
    """Return SUCCESS for enabled, DANGER for disabled toggle."""
    return ButtonStyle.SUCCESS if enabled else ButtonStyle.DANGER


def settings_kb(user: User) -> InlineKeyboardMarkup:
    """Кнопки-тогглы для каждого типа уведомлений."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"⚔️ Атаки {'✅' if user.notify_attacks else '❌'}",
        callback_data="toggle_notify_attacks",
        style=_toggle_style(user.notify_attacks),
    )
    builder.button(
        text=f"🦠 Заражения {'✅' if user.notify_infections else '❌'}",
        callback_data="toggle_notify_infections",
        style=_toggle_style(user.notify_infections),
    )
    builder.button(
        text=f"⏱ Кулдауны {'✅' if user.notify_cooldowns else '❌'}",
        callback_data="toggle_notify_cooldowns",
        style=_toggle_style(user.notify_cooldowns),
    )
    builder.button(
        text=f"🌍 Ивенты {'✅' if user.notify_events else '❌'}",
        callback_data="toggle_notify_events",
        style=_toggle_style(user.notify_events),
    )
    builder.button(text="🔙 Главное меню", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()
