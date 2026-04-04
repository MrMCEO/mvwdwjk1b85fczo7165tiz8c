"""Common reusable keyboard builders."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def back_button(callback: str = "main_menu") -> InlineKeyboardMarkup:
    """Single '◀️ Назад' button returning to the specified callback."""
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data=callback)
    return builder.as_markup()


def confirm_cancel_kb(
    confirm_callback: str,
    cancel_callback: str,
) -> InlineKeyboardMarkup:
    """Universal confirm / cancel keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=confirm_callback)
    builder.button(text="❌ Отмена", callback_data=cancel_callback)
    builder.adjust(2)
    return builder.as_markup()
