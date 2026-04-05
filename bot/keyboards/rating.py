"""Keyboards for the rating section."""

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def rating_menu_kb() -> InlineKeyboardMarkup:
    """Main rating menu — choose which leaderboard to view."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🦠 Заражения", callback_data="rating_infections", style=ButtonStyle.PRIMARY)
    builder.button(text="⚔️ Вирус", callback_data="rating_virus", style=ButtonStyle.PRIMARY)
    builder.button(text="🛡 Иммунитет", callback_data="rating_immunity", style=ButtonStyle.PRIMARY)
    builder.button(text="💰 Богатство", callback_data="rating_richest", style=ButtonStyle.PRIMARY)
    builder.button(text="◀️ Назад", callback_data="main_menu")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def rating_type_kb(rating_type: str) -> InlineKeyboardMarkup:
    """Single 'back to rating menu' button shown under a specific leaderboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ К рейтингам", callback_data="rating_menu")
    return builder.as_markup()
