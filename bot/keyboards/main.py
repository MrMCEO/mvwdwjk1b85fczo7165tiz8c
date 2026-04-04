"""Main menu keyboard."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb() -> InlineKeyboardMarkup:
    """Root navigation keyboard with all game sections."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🦠 Мой вирус",        callback_data="virus_menu")
    builder.button(text="🛡 Мой иммунитет",    callback_data="immunity_menu")
    builder.button(text="⚔️ Атаковать",        callback_data="attack_menu")
    builder.button(text="💰 Ресурсы",          callback_data="resources_menu")
    builder.button(text="🧬 Мутации",          callback_data="mutations_menu")
    builder.button(text="🔬 Лаборатория",      callback_data="lab_menu")
    builder.button(text="🏆 Рейтинг",          callback_data="rating_menu")
    builder.button(text="🏰 Альянс",           callback_data="alliance_menu")
    builder.button(text="🌍 Ивенты",           callback_data="events_menu")
    builder.button(text="🏴‍☠️ Чёрный рынок",   callback_data="market_menu")
    builder.button(text="📊 Мой профиль",      callback_data="profile")
    builder.button(text="💎 Магазин",          callback_data="shop_menu")
    # 2 per row for all rows (6 rows total)
    builder.adjust(2, 2, 2, 2, 2, 2)
    return builder.as_markup()
