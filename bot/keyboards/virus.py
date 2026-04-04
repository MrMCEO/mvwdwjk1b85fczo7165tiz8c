"""Virus section keyboards."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Human-readable branch labels
_BRANCH_LABELS = {
    "LETHALITY": "☠️ Летальность",
    "CONTAGION":  "🦠 Заразность",
    "STEALTH":    "👁 Скрытность",
}


def virus_menu_kb(upgrades: dict | None = None) -> InlineKeyboardMarkup:
    """
    Virus menu: one upgrade button per branch, then Back.

    *upgrades* – dict branch_key → {level, next_cost} (from get_virus_stats).
    When provided the button labels show current level and cost.
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
        builder.button(text=btn_text, callback_data=f"upg_v_{branch_key[:3]}")
    builder.button(text="✏️ Назвать вирус", callback_data="rename_virus")
    builder.button(text="◀️ Назад", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def virus_upgrade_kb(branch: str) -> InlineKeyboardMarkup:
    """Confirm / cancel for virus branch upgrade."""
    branch_key = branch.upper()
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Прокачать",
        callback_data=f"conf_upg_v_{branch_key[:3]}",
    )
    builder.button(text="❌ Отмена", callback_data="virus_menu")
    builder.adjust(2)
    return builder.as_markup()
