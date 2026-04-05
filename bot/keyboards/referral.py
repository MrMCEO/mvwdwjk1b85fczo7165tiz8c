"""Referral program keyboards."""

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def referral_menu_kb(has_claimable: bool) -> InlineKeyboardMarkup:
    """Main referral menu keyboard."""
    builder = InlineKeyboardBuilder()
    if has_claimable:
        builder.button(text="🎁 Забрать награду", callback_data="referral_claim_menu", style=ButtonStyle.SUCCESS)
    builder.button(text="📋 Мои рефералы", callback_data="referral_list", style=ButtonStyle.PRIMARY)
    builder.button(text="🔙 Главное меню", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def referral_claim_kb(claimable_levels: list[int]) -> InlineKeyboardMarkup:
    """Keyboard with one button per available reward level."""
    builder = InlineKeyboardBuilder()
    for level in claimable_levels:
        builder.button(
            text=f"🎁 Забрать ур. {level}",
            callback_data=f"referral_claim:{level}",
            style=ButtonStyle.SUCCESS,
        )
    builder.button(text="🔙 Назад", callback_data="referral_menu")
    builder.adjust(1)
    return builder.as_markup()


def referral_back_kb() -> InlineKeyboardMarkup:
    """Simple back-to-referral-menu keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="referral_menu")
    builder.adjust(1)
    return builder.as_markup()
