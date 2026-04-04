"""Resources section keyboard."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def resources_menu_kb() -> InlineKeyboardMarkup:
    """Resources menu: mine, daily bonus, convert, back."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⛏ Добыть",                callback_data="mine")
    builder.button(text="🎁 Ежедневный бонус",     callback_data="daily_bonus")
    builder.button(text="💱 Конвертировать premium", callback_data="convert_premium")
    builder.button(text="◀️ Назад",                 callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()
