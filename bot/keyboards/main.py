"""Main menu keyboard."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb() -> InlineKeyboardMarkup:
    """Root navigation keyboard with all game sections."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🦠 Мой вирус",      callback_data="virus_menu")
    builder.button(text="🛡 Мой иммунитет",   callback_data="immunity_menu")
    builder.button(text="⚔️ Атаковать",       callback_data="attack_menu")
    builder.button(text="💰 Ресурсы",         callback_data="resources_menu")
    builder.button(text="🏆 Рейтинг",         callback_data="rating_menu")
    builder.button(text="📊 Мой профиль",     callback_data="profile")
    builder.button(text="💎 Магазин",         callback_data="shop_menu")
    # 2 per row for the first 6, last one on its own row
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()
