"""
Alliance (clan) handlers — create, manage, join and view alliances.

FSM flows:
  - AllianceCreateStates: waiting_for_name → waiting_for_tag → confirm
  - AllianceInviteStates: waiting_for_username
  - AllianceSearchStates: waiting_for_query
  - AllianceBuyCoinsStates: waiting_for_amount
  - AllianceDonateStates: waiting_for_amount
"""

from __future__ import annotations

from html import escape

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.alliance import (
    alliance_confirm_dissolve_kb,
    alliance_confirm_leave_kb,
    alliance_info_kb,
    alliance_member_detail_kb,
    alliance_members_kb,
    alliance_no_clan_kb,
    alliance_privacy_kb,
    alliance_requests_kb,
    alliance_search_kb,
    alliance_upgrades_kb,
)
from bot.keyboards.common import back_button, confirm_cancel_kb
from bot.models.alliance import (
    PRIVACY_LABELS,
    ROLE_LABELS,
    Alliance,
    AllianceMember,
    AlliancePrivacy,
    AllianceRole,
)
from bot.services.alliance import (
    ALLIANCE_CREATE_COST,
    ALLIANCE_UPGRADE_CONFIG,
    BIO_TO_ALLIANCE_RATE,
    MAX_MEMBERS_DEFAULT,
    TREASURY_MIN_DONATION,
    buy_alliance_coins,
    convert_treasury,
    create_alliance,
    demote_member,
    dissolve_alliance,
    donate_to_treasury,
    get_alliance_info,
    get_alliance_max_members,
    get_alliance_members,
    get_alliance_upgrades,
    get_pending_requests,
    handle_request,
    invite_player,
    kick_member,
    leave_alliance,
    promote_member,
    request_join,
    search_alliances,
    set_privacy,
    upgrade_alliance,
)
from bot.services.resource import get_balance
from bot.utils.chat import dlvl, smart_reply

router = Router(name="alliance")


# ---------------------------------------------------------------------------
# FSM State groups
# ---------------------------------------------------------------------------


class AllianceCreateStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_tag = State()
    confirm = State()


class AllianceInviteStates(StatesGroup):
    waiting_for_username = State()


class AllianceSearchStates(StatesGroup):
    waiting_for_query = State()


class AllianceBuyCoinsStates(StatesGroup):
    waiting_for_amount = State()


class AllianceDonateStates(StatesGroup):
    waiting_for_amount = State()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_alliance_info(info: dict) -> str:
    """Format alliance info dict to HTML text."""
    bonus_pct = int(info["defense_bonus"] * 100)
    role_label = ROLE_LABELS.get(info["user_role"], "")
    created = info["created_at"].strftime("%d.%m.%Y") if info["created_at"] else "—"
    coins = info.get("alliance_coins", 0)
    treasury_bio = info.get("treasury_bio", 0)
    privacy = info.get("privacy", AlliancePrivacy.REQUEST)
    privacy_label = PRIVACY_LABELS.get(privacy, "📩 По запросу")

    lines = [
        f"🏰 <b>[{escape(info['tag'])}] {escape(info['name'])}</b>",
        "",
    ]

    if info.get("description"):
        lines.append(f"<i>{escape(info['description'])}</i>")
        lines.append("")

    lines += [
        "━━━━━━━━━━━━━━━",
        "👤 <b>Участники и управление</b>",
        f"  👑 Лидер: <code>{info['leader_username']}</code>",
        f"  👥 Состав: <code>{info['member_count']}/{info['max_members']}</code>",
        f"  🎖 Твоя роль: <code>{role_label}</code>",
        "",
        "💰 <b>Казна и ресурсы</b>",
        f"  🔷 AllianceCoins: <code>{coins}</code>",
        f"  🧫 Казна (bio): <code>{treasury_bio}</code>",
        "",
        "⚙️ <b>Параметры</b>",
        f"  🛡 Бонус защиты: <code>+{bonus_pct}%</code>",
        f"  {privacy_label}",
        f"  📅 Создан: <code>{created}</code>",
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Alliance menu — main entry point
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "alliance_menu")
async def cb_alliance_menu(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Show alliance info if member, otherwise show options."""
    await state.clear()

    info = await get_alliance_info(session, callback.from_user.id)

    if info is None:
        await callback.message.edit_text(
            "🏰 <b>Альянсы</b>\n\n"
            "<i>Ты не состоишь ни в одном альянсе.</i>\n\n"
            "🔰 Объединяйся с другими игроками, чтобы:\n"
            "  🛡 Получать бонусы к защите\n"
            "  💰 Копить общую казну\n"
            "  ⚔️ Участвовать в клановых ивентах\n\n"
            "Создай свой альянс или вступи в существующий!",
            reply_markup=alliance_no_clan_kb(),
            parse_mode="HTML",
        )
    else:
        pending = 0
        if info["user_role"] in (AllianceRole.LEADER, AllianceRole.OFFICER):
            reqs = await get_pending_requests(session, info["id"])
            pending = len(reqs)
        text = _fmt_alliance_info(info)
        await callback.message.edit_text(
            text,
            reply_markup=alliance_info_kb(info["user_role"], pending_requests=pending),
            parse_mode="HTML",
        )

    await callback.answer()


# ---------------------------------------------------------------------------
# Create alliance — FSM: name → tag → confirm
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "alliance_create")
async def cb_alliance_create(callback: CallbackQuery, state: FSMContext) -> None:
    """Start the create-alliance FSM."""
    await state.set_state(AllianceCreateStates.waiting_for_name)
    await callback.message.edit_text(
        f"🏰 <b>Создание альянса</b>\n\n"
        f"Стоимость создания: <b>{ALLIANCE_CREATE_COST} 🧫 BioCoins</b>\n\n"
        "Введи название альянса (3–32 символа).\n"
        "Допустимы буквы (рус/лат), цифры, пробел, _ и -:\n\n"
        "Или нажми «Назад» для отмены:",
        reply_markup=back_button("alliance_menu"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AllianceCreateStates.waiting_for_name)
async def msg_create_name(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not name:
        await smart_reply(
            message,
            "❌ Название не может быть пустым. Попробуй ещё раз:",
            reply_markup=back_button("alliance_menu"),
        )
        return

    await state.update_data(name=name)
    await state.set_state(AllianceCreateStates.waiting_for_tag)
    await smart_reply(
        message,
        f"✅ Название: <b>{escape(name)}</b>\n\n"
        "Теперь введи короткий тег альянса (2–5 символов).\n"
        "Буквы (рус/лат) и цифры, без пробелов.\n"
        "Будет отображаться как [ТЕГ] перед названием:\n\n"
        "Или нажми «Назад» для отмены:",
        reply_markup=back_button("alliance_menu"),
    )


@router.message(AllianceCreateStates.waiting_for_tag)
async def msg_create_tag(message: Message, state: FSMContext) -> None:
    tag = (message.text or "").strip()
    if not tag:
        await smart_reply(
            message,
            "❌ Тег не может быть пустым. Попробуй ещё раз:",
            reply_markup=back_button("alliance_menu"),
        )
        return

    data = await state.get_data()
    name = data.get("name", "")

    await state.update_data(tag=tag)
    await state.set_state(AllianceCreateStates.confirm)
    await smart_reply(
        message,
        f"🏰 <b>Подтверждение создания альянса</b>\n\n"
        f"Название: <b>{escape(name)}</b>\n"
        f"Тег: <b>[{escape(tag.upper())}]</b>\n"
        f"Стоимость: <b>{ALLIANCE_CREATE_COST} 🧫 BioCoins</b>\n\n"
        "Создать альянс?",
        reply_markup=confirm_cancel_kb("alliance_create_confirm", "alliance_menu"),
    )


@router.callback_query(lambda c: c.data == "alliance_create_confirm")
async def cb_alliance_create_confirm(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    data = await state.get_data()
    name = data.get("name", "")
    tag = data.get("tag", "")
    await state.clear()

    success, msg = await create_alliance(session, callback.from_user.id, name, tag)

    if success:
        info = await get_alliance_info(session, callback.from_user.id)
        role = info["user_role"] if info else AllianceRole.LEADER
        await callback.message.edit_text(
            msg,
            reply_markup=alliance_info_kb(role),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            msg,
            reply_markup=alliance_no_clan_kb(),
            parse_mode="HTML",
        )

    await callback.answer()


# ---------------------------------------------------------------------------
# Members list (paginated)
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "alliance_members")
async def cb_alliance_members(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    info = await get_alliance_info(session, callback.from_user.id)
    if info is None:
        await callback.answer("❌ Ты не в альянсе.", show_alert=True)
        return

    members = await get_alliance_members(session, info["id"])
    text = (
        f"👥 <b>Участники [{escape(info['tag'])}] {escape(info['name'])}</b>\n\n"
        f"Всего: <b>{len(members)}/{info['max_members']}</b>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=alliance_members_kb(
            members,
            viewer_role=info["user_role"],
            viewer_id=callback.from_user.id,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("alliance_members_pg_"))
async def cb_alliance_members_page(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    try:
        page = int(callback.data[len("alliance_members_pg_"):])
    except ValueError:
        page = 0
    page = max(0, page)

    info = await get_alliance_info(session, callback.from_user.id)
    if info is None:
        await callback.answer("❌ Ты не в альянсе.", show_alert=True)
        return

    members = await get_alliance_members(session, info["id"])
    text = (
        f"👥 <b>Участники [{escape(info['tag'])}] {escape(info['name'])}</b>\n\n"
        f"Всего: <b>{len(members)}/{info['max_members']}</b>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=alliance_members_kb(
            members,
            viewer_role=info["user_role"],
            viewer_id=callback.from_user.id,
            page=page,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("ally_member_"))
async def cb_ally_member_detail(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Show mini-profile for a specific alliance member + role-dependent action buttons."""
    try:
        target_id = int(callback.data[len("ally_member_"):])
    except ValueError:
        await callback.answer("❌ Неверный ID.", show_alert=True)
        return

    info = await get_alliance_info(session, callback.from_user.id)
    if info is None:
        await callback.answer("❌ Ты не в альянсе.", show_alert=True)
        return

    members = await get_alliance_members(session, info["id"])

    # Find target member in list
    target = next((m for m in members if m["user_id"] == target_id), None)
    if target is None:
        await callback.answer("❌ Участник не найден.", show_alert=True)
        return

    role_label = target["role_label"]
    uname = escape(target["username"])
    virus_lvl = target.get("virus_level", 0)
    immunity_lvl = target.get("immunity_level", 0)

    text = (
        f"👤 <b>{uname}</b>\n"
        f"🏅 Роль: <b>{role_label}</b>\n"
        f"🦠 Вирус ур. <b>{dlvl(virus_lvl)}</b>\n"
        f"🛡 Иммунитет ур. <b>{dlvl(immunity_lvl)}</b>"
    )

    # Determine which page the member is on (page_size=8)
    page_size = 8
    idx = next((i for i, m in enumerate(members) if m["user_id"] == target_id), 0)
    page = idx // page_size

    await callback.message.edit_text(
        text,
        reply_markup=alliance_member_detail_kb(
            target_id=target_id,
            target_role=target["role"],
            viewer_role=info["user_role"],
            viewer_id=callback.from_user.id,
            page=page,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Invite player — FSM
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "alliance_invite")
async def cb_alliance_invite(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(AllianceInviteStates.waiting_for_username)
    await callback.message.edit_text(
        "➕ <b>Пригласить игрока</b>\n\n"
        "Введи @username игрока которого хочешь пригласить\n"
        "(можно без символа @):\n\n"
        "Или нажми «Назад» для отмены:",
        reply_markup=back_button("alliance_menu"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AllianceInviteStates.waiting_for_username)
async def msg_invite_username(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    raw = (message.text or "").strip()
    await state.clear()

    if not raw:
        await smart_reply(
            message,
            "❌ Пустой username. Попробуй ещё раз.",
            reply_markup=back_button("alliance_menu"),
        )
        return

    success, msg = await invite_player(session, message.from_user.id, raw)
    info = await get_alliance_info(session, message.from_user.id)
    role = info["user_role"] if info else AllianceRole.MEMBER

    await smart_reply(
        message,
        msg,
        reply_markup=alliance_info_kb(role),
    )


# ---------------------------------------------------------------------------
# Kick member
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "alliance_kick_list")
async def cb_alliance_kick_list(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Show member list for kicking (redirects to the members page)."""
    info = await get_alliance_info(session, callback.from_user.id)
    if info is None:
        await callback.answer("❌ Ты не в альянсе.", show_alert=True)
        return

    members = await get_alliance_members(session, info["id"])
    text = (
        f"👥 <b>Участники [{escape(info['tag'])}] {escape(info['name'])}</b>\n\n"
        f"Всего: <b>{len(members)}/{info['max_members']}</b>\n\n"
        "Выбери участника, чтобы кикнуть его:"
    )
    await callback.message.edit_text(
        text,
        reply_markup=alliance_members_kb(
            members,
            viewer_role=info["user_role"],
            viewer_id=callback.from_user.id,
        ),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("alliance_kick_"))
async def cb_alliance_kick(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    # Skip "alliance_kick_list" — handled above
    suffix = callback.data[len("alliance_kick_"):]
    if suffix == "list":
        return

    try:
        target_id = int(suffix)
    except ValueError:
        await callback.answer("❌ Неверный ID.", show_alert=True)
        return

    success, msg = await kick_member(session, callback.from_user.id, target_id)

    if success:
        info = await get_alliance_info(session, callback.from_user.id)
        if info:
            members = await get_alliance_members(session, info["id"])
            await callback.message.edit_text(
                msg + f"\n\n👥 Участников: {len(members)}/{info['max_members']}",
                reply_markup=alliance_members_kb(
                    members,
                    viewer_role=info["user_role"],
                    viewer_id=callback.from_user.id,
                ),
                parse_mode="HTML",
            )
        else:
            await callback.message.edit_text(msg, parse_mode="HTML")
    else:
        await callback.answer(msg, show_alert=True)
        return

    await callback.answer()


# ---------------------------------------------------------------------------
# Leave alliance
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "alliance_leave")
async def cb_alliance_leave(callback: CallbackQuery, session: AsyncSession) -> None:
    info = await get_alliance_info(session, callback.from_user.id)
    if info is None:
        await callback.answer("❌ Ты не в альянсе.", show_alert=True)
        return

    is_leader = info["user_role"] == AllianceRole.LEADER
    warn = (
        "\n\n⚠️ <b>Внимание:</b> ты лидер альянса. При уходе альянс будет <b>распущен</b>!"
        if is_leader
        else ""
    )

    await callback.message.edit_text(
        f"🚪 Покинуть альянс <b>[{escape(info['tag'])}] {escape(info['name'])}</b>?{warn}",
        reply_markup=alliance_confirm_leave_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "alliance_leave_confirm")
async def cb_alliance_leave_confirm(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    success, msg = await leave_alliance(session, callback.from_user.id)

    await callback.message.edit_text(
        msg,
        reply_markup=alliance_no_clan_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Promote / demote
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data and c.data.startswith("alliance_promote_"))
async def cb_alliance_promote(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    try:
        target_id = int(callback.data[len("alliance_promote_"):])
    except ValueError:
        await callback.answer("❌ Неверный ID.", show_alert=True)
        return

    success, msg = await promote_member(session, callback.from_user.id, target_id)

    if success:
        info = await get_alliance_info(session, callback.from_user.id)
        if info:
            members = await get_alliance_members(session, info["id"])
            await callback.message.edit_text(
                msg,
                reply_markup=alliance_members_kb(
                    members,
                    viewer_role=info["user_role"],
                    viewer_id=callback.from_user.id,
                ),
                parse_mode="HTML",
            )
    else:
        await callback.answer(msg, show_alert=True)
        return

    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("alliance_demote_"))
async def cb_alliance_demote(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    try:
        target_id = int(callback.data[len("alliance_demote_"):])
    except ValueError:
        await callback.answer("❌ Неверный ID.", show_alert=True)
        return

    success, msg = await demote_member(session, callback.from_user.id, target_id)

    if success:
        info = await get_alliance_info(session, callback.from_user.id)
        if info:
            members = await get_alliance_members(session, info["id"])
            await callback.message.edit_text(
                msg,
                reply_markup=alliance_members_kb(
                    members,
                    viewer_role=info["user_role"],
                    viewer_id=callback.from_user.id,
                ),
                parse_mode="HTML",
            )
    else:
        await callback.answer(msg, show_alert=True)
        return

    await callback.answer()


# ---------------------------------------------------------------------------
# Dissolve alliance (with confirmation)
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "alliance_dissolve")
async def cb_alliance_dissolve(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    info = await get_alliance_info(session, callback.from_user.id)
    if info is None:
        await callback.answer("❌ Ты не в альянсе.", show_alert=True)
        return

    if info["user_role"] != AllianceRole.LEADER:
        await callback.answer("❌ Только лидер может распустить альянс.", show_alert=True)
        return

    await callback.message.edit_text(
        f"💀 <b>Распустить альянс [{escape(info['tag'])}] {escape(info['name'])}?</b>\n\n"
        "⚠️ Это действие <b>необратимо</b>. Все участники будут исключены.",
        reply_markup=alliance_confirm_dissolve_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "alliance_dissolve_confirm")
async def cb_alliance_dissolve_confirm(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    success, msg = await dissolve_alliance(session, callback.from_user.id)

    await callback.message.edit_text(
        msg,
        reply_markup=alliance_no_clan_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Search alliances
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "alliance_search")
async def cb_alliance_search(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Show top alliances and offer a search prompt."""
    await state.set_state(AllianceSearchStates.waiting_for_query)

    alliances = await search_alliances(session, query=None, limit=10)

    text = (
        "🔍 <b>Поиск альянсов</b>\n\n"
        "Напиши название или тег для поиска, или нажми «Назад» чтобы выйти.\n\n"
        "<b>Топ альянсов:</b>\n"
    )
    if alliances:
        lines = []
        for a in alliances:
            bonus_pct = int(a["defense_bonus"] * 100)
            lines.append(
                f"[{a['tag']}] {a['name']} — "
                f"{a['member_count']}/{a['max_members']} чел., "
                f"+{bonus_pct}% защиты"
            )
        text += "\n".join(lines)
    else:
        text += "Пока нет ни одного альянса."

    await callback.message.edit_text(
        text,
        reply_markup=alliance_search_kb(alliances),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AllianceSearchStates.waiting_for_query)
async def msg_search_query(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    query = (message.text or "").strip()
    await state.clear()

    alliances = await search_alliances(session, query=query if query else None, limit=10)

    if alliances:
        text = f"🔍 <b>Результаты поиска по «{escape(query)}»:</b>\n\n"
        lines = []
        for a in alliances:
            bonus_pct = int(a["defense_bonus"] * 100)
            lines.append(
                f"[{a['tag']}] {a['name']} — "
                f"{a['member_count']}/{a['max_members']} чел., "
                f"+{bonus_pct}% защиты"
            )
        text += "\n".join(lines)
    else:
        text = f"🔍 По запросу «{escape(query)}» ничего не найдено."

    await smart_reply(
        message,
        text,
        reply_markup=alliance_search_kb(alliances),
    )


# ---------------------------------------------------------------------------
# Join alliance
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data and c.data.startswith("alliance_join_"))
async def cb_alliance_join(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Join an OPEN alliance directly (no approval required)."""
    try:
        alliance_id = int(callback.data[len("alliance_join_"):])
    except ValueError:
        await callback.answer("❌ Неверный ID альянса.", show_alert=True)
        return

    # Check user not already in an alliance (with lock to prevent double-join race)
    existing_result = await session.execute(
        select(AllianceMember)
        .where(AllianceMember.user_id == callback.from_user.id)
        .with_for_update()
    )
    if existing_result.scalar_one_or_none() is not None:
        await callback.answer(
            "❌ Ты уже состоишь в альянсе. Сначала покинь его.", show_alert=True
        )
        return

    # Load target alliance with lock to check capacity atomically
    alliance_result = await session.execute(
        select(Alliance).where(Alliance.id == alliance_id).with_for_update()
    )
    alliance = alliance_result.scalar_one_or_none()
    if alliance is None:
        await callback.answer("❌ Альянс не найден.", show_alert=True)
        return

    # Enforce privacy: only OPEN allows direct join
    privacy_str = alliance.privacy if isinstance(alliance.privacy, str) else alliance.privacy.value
    if privacy_str == AlliancePrivacy.CLOSED.value:
        await callback.answer(
            "❌ Этот альянс закрытый — вступить можно только по приглашению.",
            show_alert=True,
        )
        return
    if privacy_str == AlliancePrivacy.REQUEST.value:
        await callback.answer(
            "❌ Этот альянс работает по заявкам. Нажми кнопку заявки.",
            show_alert=True,
        )
        return

    # Check capacity (re-count under lock)
    count_result = await session.execute(
        select(func.count(AllianceMember.id)).where(
            AllianceMember.alliance_id == alliance_id
        )
    )
    count: int = count_result.scalar_one()
    max_members = await get_alliance_max_members(session, alliance_id)
    if count >= max_members:
        await callback.answer(
            f"❌ Альянс заполнен ({count}/{max_members}).", show_alert=True
        )
        return

    new_member = AllianceMember(
        alliance_id=alliance.id,
        user_id=callback.from_user.id,
        role=AllianceRole.MEMBER,
    )
    session.add(new_member)
    await session.flush()

    info = await get_alliance_info(session, callback.from_user.id)
    role = info["user_role"] if info else AllianceRole.MEMBER

    await callback.message.edit_text(
        f"✅ Ты вступил в альянс <b>[{escape(alliance.tag)}] {escape(alliance.name)}</b>!",
        reply_markup=alliance_info_kb(role),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Upgrades screen
# ---------------------------------------------------------------------------


def _fmt_upgrades_text(info: dict, upgrades: dict) -> str:
    """Format the upgrades screen text."""
    lines = [
        f"🏰 <b>Улучшения альянса [{escape(info['tag'])}]</b>",
        f"🔷 Баланс: <code>{info['alliance_coins']}</code> AllianceCoins",
        "━━━━━━━━━━━━━━━",
        "",
    ]

    for key, data in upgrades.items():
        cfg = ALLIANCE_UPGRADE_CONFIG[key]
        level = data["level"]
        effect = data["effect"]
        next_cost = data["next_cost"]

        if key == "capacity":
            effect_str = f"{MAX_MEMBERS_DEFAULT + int(level * cfg['effect_per_level'])} слотов"
        elif key in ("shield", "morale", "mining"):
            effect_str = f"+{int(effect * 100)}%"
        else:  # regen
            effect_str = f"+{effect * 100:.0f}%"

        if level >= data["max_level"]:
            lines.append(
                f"{cfg['emoji']} {cfg['name']}: ур. <code>{dlvl(level)}</code> ({effect_str}) — <i>макс.</i>"
            )
        else:
            lines.append(
                f"{cfg['emoji']} {cfg['name']}: ур. <code>{dlvl(level)}</code> ({effect_str}) "
                f"→ ур. <code>{dlvl(level + 1)}</code> стоит <code>{next_cost}</code> 🔷"
            )

    return "\n".join(lines)


@router.callback_query(lambda c: c.data == "alliance_upgrades")
async def cb_alliance_upgrades(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Show the alliance upgrades screen."""
    info = await get_alliance_info(session, callback.from_user.id)
    if info is None:
        await callback.answer("❌ Ты не в альянсе.", show_alert=True)
        return

    if info["user_role"] not in (AllianceRole.LEADER, AllianceRole.OFFICER):
        await callback.answer("❌ Только лидер или офицер могут просматривать улучшения.", show_alert=True)
        return

    upgrades = await get_alliance_upgrades(session, info["id"])
    text = _fmt_upgrades_text(info, upgrades)

    await callback.message.edit_text(
        text,
        reply_markup=alliance_upgrades_kb(upgrades, info["user_role"], info["alliance_coins"]),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("alliance_upgrade_"))
async def cb_alliance_upgrade(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Perform a specific upgrade."""
    upgrade_key = callback.data[len("alliance_upgrade_"):]

    success, msg = await upgrade_alliance(session, callback.from_user.id, upgrade_key)

    if success:
        info = await get_alliance_info(session, callback.from_user.id)
        if info:
            upgrades = await get_alliance_upgrades(session, info["id"])
            text = _fmt_upgrades_text(info, upgrades)
            await callback.message.edit_text(
                text,
                reply_markup=alliance_upgrades_kb(upgrades, info["user_role"], info["alliance_coins"]),
                parse_mode="HTML",
            )
        else:
            await callback.message.edit_text(msg, parse_mode="HTML")
    else:
        await callback.answer(msg, show_alert=True)
        return

    await callback.answer()


# ---------------------------------------------------------------------------
# Buy AllianceCoins — FSM
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "alliance_buy_coins")
async def cb_alliance_buy_coins(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Start FSM: ask how many AllianceCoins to buy."""
    info = await get_alliance_info(session, callback.from_user.id)
    if info is None:
        await callback.answer("❌ Ты не в альянсе.", show_alert=True)
        return

    if info["user_role"] not in (AllianceRole.LEADER, AllianceRole.OFFICER):
        await callback.answer("❌ Только лидер или офицер могут покупать 🔷.", show_alert=True)
        return

    await state.set_state(AllianceBuyCoinsStates.waiting_for_amount)
    await callback.message.edit_text(
        "💎 <b>Покупка 🔷 AllianceCoins</b>\n\n"
        "Курс: <b>1 💎 PremiumCoin = 1 🔷 AllianceCoin</b>\n\n"
        "Введи количество 🔷, которое хочешь купить:\n\n"
        "Или нажми «Назад» для отмены.",
        reply_markup=back_button("alliance_upgrades"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AllianceBuyCoinsStates.waiting_for_amount)
async def msg_buy_coins_amount(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Process the entered amount and execute the purchase."""
    raw = (message.text or "").strip()
    await state.clear()

    try:
        amount = int(raw)
    except ValueError:
        await smart_reply(
            message,
            "❌ Введи целое число. Попробуй ещё раз.",
            reply_markup=back_button("alliance_upgrades"),
        )
        return

    success, msg = await buy_alliance_coins(session, message.from_user.id, amount)

    info = await get_alliance_info(session, message.from_user.id)
    if info and info["user_role"] in (AllianceRole.LEADER, AllianceRole.OFFICER):
        upgrades = await get_alliance_upgrades(session, info["id"])
        await smart_reply(
            message,
            msg + "\n\n" + _fmt_upgrades_text(info, upgrades),
            reply_markup=alliance_upgrades_kb(upgrades, info["user_role"], info["alliance_coins"]),
            parse_mode="HTML",
        )
    else:
        await smart_reply(message, msg)


# ---------------------------------------------------------------------------
# Treasury — Donate bio to alliance
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "alliance_donate")
async def cb_alliance_donate(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Start FSM: ask how many bio_coins to donate to treasury."""
    info = await get_alliance_info(session, callback.from_user.id)
    if info is None:
        await callback.answer("❌ Ты не в альянсе.", show_alert=True)
        return

    balance = await get_balance(session, callback.from_user.id)
    bio = balance.get("bio_coins", 0) if balance else 0

    await state.set_state(AllianceDonateStates.waiting_for_amount)
    await callback.message.edit_text(
        "💰 <b>Пожертвование в казну альянса</b>\n\n"
        f"💱 Курс конвертации: <code>{BIO_TO_ALLIANCE_RATE}</code> 🧫 = <code>1</code> 🔷\n"
        f"⚠️ Минимальный взнос: <code>{TREASURY_MIN_DONATION}</code> 🧫\n\n"
        "━━━━━━━━━━━━━━━\n"
        f"💰 Твой баланс: <code>{bio:,}</code> 🧫\n"
        f"🏦 Казна альянса: <code>{info['treasury_bio']:,}</code> 🧫\n\n"
        "<i>Введи сумму пожертвования (🧫 BioCoins):</i>\n\n"
        "<i>Или нажми «Назад» для отмены.</i>",
        reply_markup=back_button("alliance_menu"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AllianceDonateStates.waiting_for_amount)
async def msg_donate_amount(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Process donation amount."""
    raw = (message.text or "").strip()
    await state.clear()

    try:
        amount = int(raw)
    except ValueError:
        await smart_reply(
            message,
            "❌ Введи целое число. Попробуй ещё раз.",
            reply_markup=back_button("alliance_menu"),
        )
        return

    success, msg = await donate_to_treasury(session, message.from_user.id, amount)
    info = await get_alliance_info(session, message.from_user.id)
    role = info["user_role"] if info else AllianceRole.MEMBER

    # Count pending requests for badge
    pending = 0
    if info and role in (AllianceRole.LEADER, AllianceRole.OFFICER):
        reqs = await get_pending_requests(session, info["id"])
        pending = len(reqs)

    await smart_reply(
        message,
        msg,
        reply_markup=alliance_info_kb(role, pending_requests=pending),
    )


# ---------------------------------------------------------------------------
# Treasury — Convert treasury (leader/officer)
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "alliance_convert_treasury")
async def cb_alliance_convert_treasury(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Convert accumulated treasury_bio into alliance_coins."""
    success, msg = await convert_treasury(session, callback.from_user.id)

    if success:
        info = await get_alliance_info(session, callback.from_user.id)
        role = info["user_role"] if info else AllianceRole.MEMBER
        pending = 0
        if info and role in (AllianceRole.LEADER, AllianceRole.OFFICER):
            reqs = await get_pending_requests(session, info["id"])
            pending = len(reqs)
        text = msg + "\n\n" + _fmt_alliance_info(info)
        await callback.message.edit_text(
            text,
            reply_markup=alliance_info_kb(role, pending_requests=pending),
            parse_mode="HTML",
        )
    else:
        await callback.answer(msg, show_alert=True)
        return

    await callback.answer()


# ---------------------------------------------------------------------------
# Privacy — set alliance privacy mode (leader only)
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "alliance_privacy")
async def cb_alliance_privacy(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Show privacy selection keyboard."""
    info = await get_alliance_info(session, callback.from_user.id)
    if info is None:
        await callback.answer("❌ Ты не в альянсе.", show_alert=True)
        return

    if info["user_role"] != AllianceRole.LEADER:
        await callback.answer("❌ Только лидер может менять приватность.", show_alert=True)
        return

    current_privacy = info.get("privacy", AlliancePrivacy.REQUEST)
    await callback.message.edit_text(
        f"⚙️ <b>Приватность альянса [{escape(info['tag'])}] {escape(info['name'])}</b>\n\n"
        "🔒 <b>Закрытый</b> — вступить можно только по приглашению лидера/офицера.\n"
        "📩 <b>По запросу</b> — игроки подают заявку, офицеры принимают/отклоняют.\n"
        "🔓 <b>Открытый</b> — любой может вступить без одобрения.\n\n"
        "Текущий режим выделен ✅:",
        reply_markup=alliance_privacy_kb(current_privacy),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("alliance_set_privacy_"))
async def cb_set_privacy(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Apply selected privacy mode."""
    mode_str = callback.data[len("alliance_set_privacy_"):]
    try:
        privacy = AlliancePrivacy(mode_str)
    except ValueError:
        await callback.answer("❌ Неизвестный режим.", show_alert=True)
        return

    success, msg = await set_privacy(session, callback.from_user.id, privacy)

    if success:
        info = await get_alliance_info(session, callback.from_user.id)
        if info:
            current_privacy = info.get("privacy", AlliancePrivacy.REQUEST)
            await callback.message.edit_text(
                f"⚙️ <b>Приватность альянса [{escape(info['tag'])}] {escape(info['name'])}</b>\n\n"
                "🔒 <b>Закрытый</b> — вступить можно только по приглашению лидера/офицера.\n"
                "📩 <b>По запросу</b> — игроки подают заявку, офицеры принимают/отклоняют.\n"
                "🔓 <b>Открытый</b> — любой может вступить без одобрения.\n\n"
                f"{msg}\n\nТекущий режим выделен ✅:",
                reply_markup=alliance_privacy_kb(current_privacy),
                parse_mode="HTML",
            )
    else:
        await callback.answer(msg, show_alert=True)
        return

    await callback.answer()


# ---------------------------------------------------------------------------
# Privacy — REQUEST mode: join requests flow
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data and c.data.startswith("alliance_request_"))
async def cb_alliance_request_join(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Submit a join request for a REQUEST-mode alliance."""
    try:
        alliance_id = int(callback.data[len("alliance_request_"):])
    except ValueError:
        await callback.answer("❌ Неверный ID альянса.", show_alert=True)
        return

    success, msg = await request_join(session, callback.from_user.id, alliance_id)

    if success:
        # Notification will be sent by main.py bot instance — pass bot via DI
        # For now just show the user the result
        await callback.message.edit_text(
            msg,
            reply_markup=alliance_no_clan_kb(),
            parse_mode="HTML",
        )
    else:
        await callback.answer(msg, show_alert=True)
        return

    await callback.answer()


@router.callback_query(lambda c: c.data == "alliance_requests")
async def cb_alliance_requests(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Show pending join requests list for the alliance."""
    info = await get_alliance_info(session, callback.from_user.id)
    if info is None:
        await callback.answer("❌ Ты не в альянсе.", show_alert=True)
        return

    if info["user_role"] not in (AllianceRole.LEADER, AllianceRole.OFFICER):
        await callback.answer("❌ Только лидер или офицер могут смотреть заявки.", show_alert=True)
        return

    requests = await get_pending_requests(session, info["id"])
    text = (
        f"📩 <b>Заявки на вступление в [{escape(info['tag'])}] {escape(info['name'])}</b>\n\n"
        f"Активных заявок: <b>{len(requests)}</b>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=alliance_requests_kb(requests),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("alliance_req_info_"))
async def cb_req_info_noop(callback: CallbackQuery) -> None:
    """Noop — request username button is a label."""
    await callback.answer("Нажми ✅ Принять или ❌ Отклонить рядом с заявкой.")


@router.callback_query(lambda c: c.data and c.data.startswith("alliance_req_accept_"))
async def cb_req_accept(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Accept a join request."""
    try:
        request_id = int(callback.data[len("alliance_req_accept_"):])
    except ValueError:
        await callback.answer("❌ Неверный ID заявки.", show_alert=True)
        return

    success, msg = await handle_request(session, callback.from_user.id, request_id, accept=True)

    if success:
        info = await get_alliance_info(session, callback.from_user.id)
        if info:
            requests = await get_pending_requests(session, info["id"])
            text = (
                f"📩 <b>Заявки на вступление в [{escape(info['tag'])}] {escape(info['name'])}</b>\n\n"
                f"{msg}\n\nАктивных заявок: <b>{len(requests)}</b>"
            )
            await callback.message.edit_text(
                text,
                reply_markup=alliance_requests_kb(requests),
                parse_mode="HTML",
            )
    else:
        await callback.answer(msg, show_alert=True)
        return

    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("alliance_req_decline_"))
async def cb_req_decline(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Decline a join request."""
    try:
        request_id = int(callback.data[len("alliance_req_decline_"):])
    except ValueError:
        await callback.answer("❌ Неверный ID заявки.", show_alert=True)
        return

    success, msg = await handle_request(session, callback.from_user.id, request_id, accept=False)

    if success:
        info = await get_alliance_info(session, callback.from_user.id)
        if info:
            requests = await get_pending_requests(session, info["id"])
            text = (
                f"📩 <b>Заявки на вступление в [{escape(info['tag'])}] {escape(info['name'])}</b>\n\n"
                f"{msg}\n\nАктивных заявок: <b>{len(requests)}</b>"
            )
            await callback.message.edit_text(
                text,
                reply_markup=alliance_requests_kb(requests),
                parse_mode="HTML",
            )
    else:
        await callback.answer(msg, show_alert=True)
        return

    await callback.answer()


# ---------------------------------------------------------------------------
# Join alliance — updated: respects privacy (OPEN = direct join, REQUEST = request)
# The existing cb_alliance_join handles OPEN mode (direct join).
# alliance_request_ prefix handles REQUEST mode (join request).
# ---------------------------------------------------------------------------
