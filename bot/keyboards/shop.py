"""Shop section keyboard."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def shop_menu_kb() -> InlineKeyboardMarkup:
    """
    Shop menu.

    Premium-coin purchase options are stubs until payment integration is ready.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="💎 50 premium  [заглушка]",  callback_data="buy_p_50")
    builder.button(text="💎 150 premium [заглушка]",  callback_data="buy_p_150")
    builder.button(text="💎 500 premium [заглушка]",  callback_data="buy_p_500")
    builder.button(text="💱 Конвертировать premium→bio", callback_data="shop_convert_premium")
    builder.button(text="◀️ Назад",                    callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()
