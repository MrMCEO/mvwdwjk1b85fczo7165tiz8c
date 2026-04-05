"""Attack section keyboards."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

_PAGE_SIZE = 5


def attack_menu_kb() -> InlineKeyboardMarkup:
    """Attack menu: enter target username, random attack, view infections, back."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⚔️ Ввести цель (@username)", callback_data="attack_enter")
    builder.button(text="🎲 Случайная атака",          callback_data="random_attack")
    builder.button(text="🦠 Мои заражения",            callback_data="my_infections")
    builder.button(text="◀️ Назад",                    callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def attack_confirm_kb(victim_id: int) -> InlineKeyboardMarkup:
    """Confirm / cancel attack on specific victim."""
    builder = InlineKeyboardBuilder()
    # callback_data must be ≤ 64 bytes
    builder.button(text="⚔️ Атаковать!", callback_data=f"atk_{victim_id}")
    builder.button(text="❌ Отмена",     callback_data="attack_menu")
    builder.adjust(2)
    return builder.as_markup()


def infections_list_kb(
    infections: list,
    page: int = 0,
    mode: str = "by",  # "by" = outgoing, "on" = incoming
) -> InlineKeyboardMarkup:
    """
    Paginated list of infections.

    Each row shows one infection with a 'Cure' button (incoming only).
    Navigation buttons at the bottom.
    """
    builder = InlineKeyboardBuilder()

    start = page * _PAGE_SIZE
    end = start + _PAGE_SIZE
    page_items = infections[start:end]

    for inf in page_items:
        if mode == "on":
            # Incoming infections — show cure button
            label = f"🔬 #{inf.id} — урон {inf.damage_per_tick:.1f}/тик  → Вылечить"
            builder.button(text=label, callback_data=f"cure_{inf.id}")
        else:
            # Outgoing infections — info only
            label = f"🦠 #{inf.id} — жертва {inf.victim_id}, урон {inf.damage_per_tick:.1f}/тик"
            builder.button(text=label, callback_data=f"inf_info_{inf.id}")

    builder.adjust(1)

    # Build nav row inline
    total_pages = max(1, (len(infections) + _PAGE_SIZE - 1) // _PAGE_SIZE)
    nav_builder = InlineKeyboardBuilder()
    if page > 0:
        nav_builder.button(text="◀", callback_data=f"inf_pg_{mode}_{page - 1}")
    nav_builder.button(text=f"{page + 1}/{total_pages}", callback_data="noop")
    if end < len(infections):
        nav_builder.button(text="▶", callback_data=f"inf_pg_{mode}_{page + 1}")
    nav_builder.adjust(3)

    # Merge nav row
    for row in nav_builder.export():
        builder.row(*row)

    # Back button
    builder.row(
        InlineKeyboardButton(text="◀️ Назад", callback_data="attack_menu")
    )

    return builder.as_markup()
