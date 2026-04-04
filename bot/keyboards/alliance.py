"""Alliance section keyboards."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.models.alliance import PRIVACY_LABELS, AlliancePrivacy, AllianceRole
from bot.services.alliance import ALLIANCE_UPGRADE_CONFIG


def alliance_no_clan_kb() -> InlineKeyboardMarkup:
    """Keyboard shown when the player is not in any alliance."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🏰 Создать альянс", callback_data="alliance_create")
    builder.button(text="🔍 Найти альянс",   callback_data="alliance_search")
    builder.button(text="◀️ Назад",          callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def alliance_info_kb(role: AllianceRole, pending_requests: int = 0) -> InlineKeyboardMarkup:
    """
    Keyboard shown on the alliance info page.

    Buttons depend on the viewer's role:
    - Everyone: Участники, 💰 Пожертвовать, Покинуть, Назад
    - LEADER/OFFICER: + Пригласить, Кикнуть, Улучшения, 💱 Конвертировать, Заявки
    - LEADER only: + ⚙️ Приватность, Распустить
    """
    builder = InlineKeyboardBuilder()

    builder.button(text="👥 Участники",           callback_data="alliance_members")
    builder.button(text="💰 Пожертвовать",         callback_data="alliance_donate")

    if role in (AllianceRole.LEADER, AllianceRole.OFFICER):
        builder.button(text="➕ Пригласить",       callback_data="alliance_invite")
        builder.button(text="🚫 Кикнуть",          callback_data="alliance_kick_list")
        builder.button(text="🔧 Улучшения",        callback_data="alliance_upgrades")
        builder.button(text="💱 Конвертировать казну", callback_data="alliance_convert_treasury")

        req_label = (
            f"📩 Заявки ({pending_requests})" if pending_requests > 0
            else "📩 Заявки"
        )
        builder.button(text=req_label, callback_data="alliance_requests")

    if role == AllianceRole.LEADER:
        builder.button(text="⚙️ Приватность",      callback_data="alliance_privacy")
        builder.button(text="💀 Распустить",        callback_data="alliance_dissolve")

    builder.button(text="🚪 Покинуть",              callback_data="alliance_leave")
    builder.button(text="◀️ Назад",                 callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def alliance_privacy_kb(current: AlliancePrivacy) -> InlineKeyboardMarkup:
    """Keyboard to select privacy mode."""
    builder = InlineKeyboardBuilder()
    for mode in AlliancePrivacy:
        marker = "✅ " if mode == current else ""
        label = PRIVACY_LABELS[mode]
        builder.button(
            text=f"{marker}{label}",
            callback_data=f"alliance_set_privacy_{mode.value}",
        )
    builder.button(text="◀️ Назад", callback_data="alliance_menu")
    builder.adjust(1)
    return builder.as_markup()


def alliance_requests_kb(requests: list[dict]) -> InlineKeyboardMarkup:
    """
    Keyboard listing pending join requests with Accept / Decline buttons.
    Each request dict has: request_id, username.
    """
    builder = InlineKeyboardBuilder()

    if not requests:
        builder.button(text="Нет активных заявок", callback_data="noop")
    else:
        for req in requests:
            rid = req["request_id"]
            uname = req["username"]
            builder.button(
                text=f"👤 @{uname}",
                callback_data=f"alliance_req_info_{rid}",
            )
            builder.button(
                text="✅ Принять",
                callback_data=f"alliance_req_accept_{rid}",
            )
            builder.button(
                text="❌ Отклонить",
                callback_data=f"alliance_req_decline_{rid}",
            )

    builder.button(text="◀️ Назад", callback_data="alliance_menu")

    if requests:
        # Group: name button (full row) + two action buttons per request
        row_scheme = []
        for _ in requests:
            row_scheme += [1, 2]  # 1 name row, then 2 action buttons
        row_scheme.append(1)  # Back button
        builder.adjust(*row_scheme)
    else:
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
    List of alliances with 'Вступить' / 'Подать заявку' buttons.

    Each alliance shows: [TAG] Name (members/max) + privacy icon.
    """
    builder = InlineKeyboardBuilder()

    for a in alliances:
        privacy = a.get("privacy", AlliancePrivacy.REQUEST)
        if privacy == AlliancePrivacy.OPEN:
            icon = "🔓"
            action_cb = f"alliance_join_{a['id']}"
        else:
            # REQUEST mode (CLOSED is filtered out by search_alliances)
            icon = "📩"
            action_cb = f"alliance_request_{a['id']}"

        label = (
            f"{icon} [{a['tag']}] {a['name']} "
            f"({a['member_count']}/{a['max_members']})"
        )
        builder.button(text=label, callback_data=action_cb)

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


def alliance_upgrades_kb(
    upgrades: dict,
    role: AllianceRole,
    balance: int,
) -> InlineKeyboardMarkup:
    """
    Upgrade screen keyboard.

    Shows one button per upgrade (disabled/max label if maxed).
    For LEADER/OFFICER: includes 'Buy AllianceCoins' button.
    Always includes Back button.
    """
    builder = InlineKeyboardBuilder()

    for key, data in upgrades.items():
        cfg = ALLIANCE_UPGRADE_CONFIG[key]
        level = data["level"]
        max_level = data["max_level"]

        if level >= max_level:
            label = f"{cfg['emoji']} {cfg['name']}: МАКС ({max_level})"
        else:
            next_cost = data["next_cost"]
            can_afford = "✅" if balance >= next_cost else "❌"
            label = f"{can_afford} {cfg['emoji']} {cfg['name']}: ур.{level} → {next_cost} 🔷"

        builder.button(text=label, callback_data=f"alliance_upgrade_{key}")

    if role in (AllianceRole.LEADER, AllianceRole.OFFICER):
        builder.button(text="💎 Купить 🔷 AllianceCoins", callback_data="alliance_buy_coins")

    builder.button(text="◀️ Назад", callback_data="alliance_menu")
    builder.adjust(1)
    return builder.as_markup()
