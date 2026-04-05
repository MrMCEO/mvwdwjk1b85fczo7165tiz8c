"""Transfer section keyboards — peer-to-peer bio_coin transfers."""

from __future__ import annotations

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def transfer_menu_kb(daily_used: int, daily_limit: int) -> InlineKeyboardMarkup:
    """Main transfer menu keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="💸 Перевести монеты", callback_data="transfer_start", style=ButtonStyle.SUCCESS)
    builder.button(text="◀️ Назад", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def transfer_confirm_kb(username: str, amount: int, received: int, commission: int) -> InlineKeyboardMarkup:
    """Confirmation keyboard before executing the transfer."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"✅ Перевести {amount} 🧫 → @{username}",
        callback_data="transfer_confirm",
        style=ButtonStyle.SUCCESS,
    )
    builder.button(text="❌ Отмена", callback_data="transfer_menu", style=ButtonStyle.DANGER)
    builder.adjust(1)
    return builder.as_markup()


def transfer_back_kb() -> InlineKeyboardMarkup:
    """Simple back button to transfer menu."""
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data="transfer_menu")
    return builder.as_markup()
