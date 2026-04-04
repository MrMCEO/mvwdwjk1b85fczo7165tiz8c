"""Immunity section keyboards."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

_BRANCH_LABELS = {
    "BARRIER":      "🛡 Барьер",
    "DETECTION":    "🔍 Детекция",
    "REGENERATION": "💊 Регенерация",
}


def immunity_menu_kb(upgrades: dict | None = None) -> InlineKeyboardMarkup:
    """
    Immunity menu: one upgrade button per branch, then Back.

    *upgrades* – dict branch_key → {level, next_cost} (from get_immunity_stats).
    """
    builder = InlineKeyboardBuilder()
    for branch_key, label in _BRANCH_LABELS.items():
        if upgrades:
            info = upgrades.get(branch_key, {})
            lvl = info.get("level", 0)
            cost = info.get("next_cost")
            if cost is None:
                btn_text = f"{label}  [Ур.{lvl}] — МАКС"
            else:
                btn_text = f"{label}  [Ур.{lvl}] — {cost} bio"
        else:
            btn_text = label
        builder.button(text=btn_text, callback_data=f"upg_i_{branch_key[:3]}")
    builder.button(text="◀️ Назад", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def immunity_upgrade_kb(branch: str) -> InlineKeyboardMarkup:
    """Confirm / cancel for immunity branch upgrade."""
    branch_key = branch.upper()
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Прокачать",
        callback_data=f"conf_upg_i_{branch_key[:3]}",
    )
    builder.button(text="❌ Отмена", callback_data="immunity_menu")
    builder.adjust(2)
    return builder.as_markup()
