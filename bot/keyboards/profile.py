"""Keyboards for the profile section."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def profile_kb() -> InlineKeyboardMarkup:
    """Profile view — links to activity logs and back button."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Лог атак", callback_data="attack_log:0")
    builder.button(text="💰 Лог транзакций", callback_data="transaction_log:0")
    builder.button(text="◀️ Назад", callback_data="main_menu")
    builder.adjust(2, 1)
    return builder.as_markup()


def log_pagination_kb(
    log_type: str,
    page: int,
    has_next: bool,
) -> InlineKeyboardMarkup:
    """
    Pagination keyboard for attack / transaction logs.

    log_type: "attack_log" | "transaction_log"
    page: current 0-based page number
    has_next: whether a next page exists
    """
    builder = InlineKeyboardBuilder()

    if page > 0:
        builder.button(text="◀️ Пред.", callback_data=f"{log_type}:{page - 1}")

    if has_next:
        builder.button(text="След. ▶️", callback_data=f"{log_type}:{page + 1}")

    if page > 0 or has_next:
        builder.adjust(2)

    builder.row(
        InlineKeyboardButton(text="📊 Профиль", callback_data="profile"),
        InlineKeyboardButton(text="◀️ Назад", callback_data="main_menu"),
    )
    return builder.as_markup()
