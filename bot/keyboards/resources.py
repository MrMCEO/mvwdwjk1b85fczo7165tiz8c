"""Resources section keyboard."""

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def resources_menu_kb() -> InlineKeyboardMarkup:
    """Resources menu: mine (SUCCESS), daily bonus, convert (PRIMARY), back."""
    builder = InlineKeyboardBuilder()
    # Mine — SUCCESS
    builder.button(text="⛏ Добыть ресурсы", callback_data="mine", style=ButtonStyle.SUCCESS)
    # Daily bonus — mono
    builder.button(text="🎁 Ежедневный бонус", callback_data="daily_bonus")
    # Convert — PRIMARY
    builder.button(text="💱 Конвертировать 💎 → 🧫", callback_data="convert_premium", style=ButtonStyle.PRIMARY)
    # Back — mono
    builder.button(text="🔙 Главное меню", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()
