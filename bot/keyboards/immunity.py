"""Immunity section keyboards."""

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

_BRANCH_LABELS = {
    "BARRIER":      ("🛡", "Барьер"),
    "DETECTION":    ("🔍", "Детекция"),
    "REGENERATION": ("💊", "Регенерация"),
}


def immunity_menu_kb(upgrades: dict | None = None) -> InlineKeyboardMarkup:
    """
    Immunity menu: upgrade buttons (2 per row), then Back.

    *upgrades* – dict branch_key → {level, next_cost} (from get_immunity_stats).
    """
    builder = InlineKeyboardBuilder()

    branch_keys = list(_BRANCH_LABELS.keys())

    for branch_key in branch_keys:
        icon, name = _BRANCH_LABELS[branch_key]
        if upgrades:
            info = upgrades.get(branch_key, {})
            lvl = info.get("level", 0)
            cost = info.get("next_cost")
            if cost is None:
                btn_text = f"{icon} {name} [Ур.{lvl}] МАКС"
            else:
                btn_text = f"{icon} {name} ⬆️ {cost}🧫"
        else:
            btn_text = f"{icon} {name} ⬆️"
        builder.button(
            text=btn_text,
            callback_data=f"upg_i_{branch_key[:3]}",
            style=ButtonStyle.SUCCESS,
        )

    # Back — mono
    builder.button(text="🔙 Главное меню", callback_data="main_menu")

    # 3 upgrade buttons: 2 + 1, then back mono
    builder.adjust(2, 1, 1)
    return builder.as_markup()


def immunity_upgrade_kb(branch: str) -> InlineKeyboardMarkup:
    """Confirm / cancel for immunity branch upgrade."""
    branch_key = branch.upper()
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Прокачать",
        callback_data=f"conf_upg_i_{branch_key[:3]}",
        style=ButtonStyle.SUCCESS,
    )
    builder.button(text="❌ Отмена", callback_data="immunity_menu", style=ButtonStyle.DANGER)
    builder.adjust(2)
    return builder.as_markup()
