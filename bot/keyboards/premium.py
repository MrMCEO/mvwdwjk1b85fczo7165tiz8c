"""Premium subscription keyboards."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def premium_menu_kb(is_active: bool) -> InlineKeyboardMarkup:
    """
    Keyboard for the premium info/menu screen.

    is_active=True  → "Продлить за 200 💎" + "✏️ Установить префикс" buttons
    is_active=False → "Купить за 200 💎" button
    Both variants include a "Назад" button.
    """
    builder = InlineKeyboardBuilder()
    if is_active:
        builder.button(text="🔄 Продлить за 200 💎", callback_data="premium_buy")
        builder.button(text="✏️ Установить префикс", callback_data="premium_set_prefix")
    else:
        builder.button(text="⭐ Купить за 200 💎", callback_data="premium_buy")
    builder.button(text="◀️ Назад", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def premium_confirm_kb() -> InlineKeyboardMarkup:
    """Confirmation keyboard for premium purchase."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Купить за 200 💎", callback_data="premium_confirm")
    builder.button(text="❌ Отмена", callback_data="premium_menu")
    builder.adjust(1)
    return builder.as_markup()
