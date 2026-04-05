"""Keyboards for the profile section."""

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def profile_kb() -> InlineKeyboardMarkup:
    """Profile view — links to activity logs, display name, and back button."""
    builder = InlineKeyboardBuilder()
    # Row 1: attack logs — PRIMARY
    builder.button(text="📝 Логи атак", callback_data="attack_log:0", style=ButtonStyle.PRIMARY)
    # Row 2: transactions + rename — 2 in a row; transactions PRIMARY
    builder.button(text="📋 Транзакции", callback_data="transaction_log:0", style=ButtonStyle.PRIMARY)
    builder.button(text="✏️ Имя", callback_data="set_display_name", style=ButtonStyle.PRIMARY)
    # Row 3: back — mono
    builder.button(text="🔙 Главное меню", callback_data="main_menu")
    builder.adjust(1, 2, 1)
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
    )
    builder.row(
        InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu"),
    )
    return builder.as_markup()
