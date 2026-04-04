"""Alliance section keyboards."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.models.alliance import AllianceRole


def alliance_no_clan_kb() -> InlineKeyboardMarkup:
    """Keyboard shown when the player is not in any alliance."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏰 Создать альянс", callback_data="alliance_create")
    builder.button(text="🔍 Найти альянс",   callback_data="alliance_search")
    builder.button(text="◀️ Назад",          callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def alliance_info_kb(role: AllianceRole) -> InlineKeyboardMarkup:
    """
    Keyboard shown on the alliance info page.

    Buttons depend on the viewer's role:
    - Everyone: Участники, Покинуть, Назад
    - LEADER/OFFICER: + Пригласить, Кикнуть
    - LEADER only: + Распустить
    """
    builder = InlineKeyboardBuilder()

    builder.button(text="👥 Участники",       callback_data="alliance_members")

    if role in (AllianceRole.LEADER, AllianceRole.OFFICER):
        builder.button(text="➕ Пригласить",  callback_data="alliance_invite")
        builder.button(text="🚫 Кикнуть",     callback_data="alliance_kick_list")

    builder.button(text="🚪 Покинуть",        callback_data="alliance_leave")

    if role == AllianceRole.LEADER:
        builder.button(text="💀 Распустить",  callback_data="alliance_dissolve")

    builder.button(text="◀️ Назад",           callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def alliance_members_kb(
    members: list[dict],
    viewer_role: AllianceRole,
    viewer_id: int,
    page: int = 0,
    page_size: int = 8,
) -> InlineKeyboardMarkup:
    """
    Paginated list of alliance members with action buttons.

    For LEADER: each OFFICER/MEMBER row has Понизить/Исключить buttons.
    For OFFICER: each MEMBER row has Исключить button.
    Navigation at the bottom.
    """
    builder = InlineKeyboardBuilder()

    start = page * page_size
    end = start + page_size
    page_items = members[start:end]
    total_pages = max(1, (len(members) + page_size - 1) // page_size)

    for m in page_items:
        uid = m["user_id"]
        uname = m["username"]
        role_icon = {
            AllianceRole.LEADER: "👑",
            AllianceRole.OFFICER: "⚔️",
            AllianceRole.MEMBER: "👤",
        }[m["role"]]

        # Info row (non-clickable label styled as info)
        builder.button(
            text=f"{role_icon} {uname}",
            callback_data=f"alliance_member_info_{uid}",
        )

        # Action buttons for managers (skip self)
        if uid != viewer_id:
            if viewer_role == AllianceRole.LEADER:
                if m["role"] == AllianceRole.MEMBER:
                    builder.button(
                        text="⬆️ Повысить", callback_data=f"alliance_promote_{uid}"
                    )
                elif m["role"] == AllianceRole.OFFICER:
                    builder.button(
                        text="⬇️ Понизить", callback_data=f"alliance_demote_{uid}"
                    )
                if m["role"] != AllianceRole.LEADER:
                    builder.button(
                        text="🚫 Кик", callback_data=f"alliance_kick_{uid}"
                    )
            elif viewer_role == AllianceRole.OFFICER and m["role"] == AllianceRole.MEMBER:
                builder.button(
                    text="🚫 Кик", callback_data=f"alliance_kick_{uid}"
                )

    builder.adjust(1)

    # Navigation row
    nav_builder = InlineKeyboardBuilder()
    if page > 0:
        nav_builder.button(text="◀", callback_data=f"alliance_members_pg_{page - 1}")
    nav_builder.button(text=f"{page + 1}/{total_pages}", callback_data="noop")
    if end < len(members):
        nav_builder.button(text="▶", callback_data=f"alliance_members_pg_{page + 1}")
    if len(nav_builder.export()) > 0:
        for row in nav_builder.export():
            builder.row(*row)

    builder.row(
        *InlineKeyboardBuilder()
        .button(text="◀️ Назад", callback_data="alliance_menu")
        .export()[0]
    )

    return builder.as_markup()


def alliance_search_kb(alliances: list[dict]) -> InlineKeyboardMarkup:
    """
    List of alliances with 'Вступить' buttons.

    Each alliance shows: [TAG] Name (members/max).
    """
    builder = InlineKeyboardBuilder()

    for a in alliances:
        label = (
            f"[{a['tag']}] {a['name']} "
            f"({a['member_count']}/{a['max_members']})"
        )
        builder.button(text=label, callback_data=f"alliance_join_{a['id']}")

    if not alliances:
        builder.button(text="Альянсов не найдено", callback_data="noop")

    builder.button(text="◀️ Назад", callback_data="alliance_menu")
    builder.adjust(1)
    return builder.as_markup()


def alliance_confirm_dissolve_kb() -> InlineKeyboardMarkup:
    """Confirmation keyboard for dissolving the alliance."""
    builder = InlineKeyboardBuilder()
    builder.button(text="💀 Да, распустить", callback_data="alliance_dissolve_confirm")
    builder.button(text="❌ Отмена",          callback_data="alliance_menu")
    builder.adjust(2)
    return builder.as_markup()


def alliance_confirm_leave_kb() -> InlineKeyboardMarkup:
    """Confirmation keyboard for leaving the alliance."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🚪 Да, покинуть", callback_data="alliance_leave_confirm")
    builder.button(text="❌ Отмена",        callback_data="alliance_menu")
    builder.adjust(2)
    return builder.as_markup()
