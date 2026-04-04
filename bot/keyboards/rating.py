"""Keyboards for the rating section."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def rating_menu_kb() -> InlineKeyboardMarkup:
    """Main rating menu — choose which leaderboard to view."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🦠 Заражения", callback_data="rating_infections")
    builder.button(text="⚔️ Вирус", callback_data="rating_virus")
    builder.button(text="🛡 Иммунитет", callback_data="rating_immunity")
    builder.button(text="💰 Богатство", callback_data="rating_richest")
    builder.button(text="◀️ Назад", callback_data="main_menu")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def rating_type_kb(rating_type: str) -> InlineKeyboardMarkup:
    """Single 'back to rating menu' button shown under a specific leaderboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ К рейтингам", callback_data="rating_menu")
    return builder.as_markup()
