"""Virus section keyboards."""

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# Human-readable branch labels with emoji
_BRANCH_LABELS = {
    "LETHALITY": ("☠️", "Летальность"),
    "CONTAGION":  ("🦠", "Заразность"),
    "STEALTH":    ("👁", "Скрытность"),
}


def virus_menu_kb(upgrades: dict | None = None) -> InlineKeyboardMarkup:
    """
    Virus menu: upgrade buttons (2 per row), rename, and Back.

    *upgrades* – dict branch_key → {level, next_cost} (from get_virus_stats).
    When provided the button labels show current level and cost.
    """
    builder = InlineKeyboardBuilder()

    branch_keys = list(_BRANCH_LABELS.keys())

    # Build pairs of upgrade buttons (2 per row)
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
            callback_data=f"upg_v_{branch_key[:3]}",
            style=ButtonStyle.SUCCESS,
        )

    # Rename — mono
    builder.button(text="✏️ Переименовать", callback_data="rename_virus")
    # Back — mono
    builder.button(text="🔙 Главное меню", callback_data="main_menu")

    # 3 upgrade buttons: 2 + 1, then rename mono, back mono
    builder.adjust(2, 1, 1, 1)
    return builder.as_markup()


def virus_upgrade_kb(branch: str) -> InlineKeyboardMarkup:
    """Confirm / cancel for virus branch upgrade."""
    branch_key = branch.upper()
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Прокачать",
        callback_data=f"conf_upg_v_{branch_key[:3]}",
        style=ButtonStyle.SUCCESS,
    )
    builder.button(text="❌ Отмена", callback_data="virus_menu", style=ButtonStyle.DANGER)
    builder.adjust(2)
    return builder.as_markup()
