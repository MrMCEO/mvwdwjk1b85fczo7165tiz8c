"""
Admin panel handlers.

All admin commands require the user to be in ADMIN_IDS (checked by _is_admin()).
The only exception is /promo — accessible to all players.

FSM flows:
  - AdminFindPlayer: waiting_for_identifier
  - AdminGiveCurrency: waiting_for_give_input
  - AdminSetBalance: waiting_for_setbal_input
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from html import escape

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.keyboards.admin import (
    EVENT_EMOJI,
    EVENT_NAMES,
    admin_event_detail_kb,
    admin_event_duration_kb,
    admin_event_stop_confirm_kb,
    admin_event_types_kb,
    admin_events_kb,
    admin_logs_kb,
    admin_menu_kb,
    admin_pandemic_hp_kb,
    admin_player_kb,
    admin_promo_detail_kb,
    admin_promos_kb,
    cancel_kb,
    confirm_give_kb,
)
from bot.models.alliance import Alliance
from bot.models.event import EventType
from bot.models.infection import Infection
from bot.models.promo import PromoCode
from bot.models.user import User
from bot.services.admin import get_player_logs, give_currency, lookup_player, set_balance
from bot.services.event import (
    create_event,
    get_active_events,
    get_event_by_id,
    start_pandemic,
    stop_event,
)
from bot.services.promo import (
    activate_promo,
    create_promo,
    delete_promo,
    get_promo_info,
    list_promos,
)

logger = logging.getLogger(__name__)
router = Router(name="admin")


# ---------------------------------------------------------------------------
# Auth helper
# ---------------------------------------------------------------------------


def _is_admin(user_id: int) -> bool:
    return user_id in get_settings().admin_ids


# ---------------------------------------------------------------------------
# FSM State groups
# ---------------------------------------------------------------------------


class AdminFindPlayer(StatesGroup):
    waiting_for_identifier = State()


class AdminGiveCurrency(StatesGroup):
    waiting_for_input = State()


class AdminSetBalance(StatesGroup):
    waiting_for_input = State()


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

_BRANCH_EMOJI = {
    "LETHALITY": "☠️",
    "CONTAGION": "🦠",
    "STEALTH": "👁",
    "BARRIER": "🛡",
    "DETECTION": "🔍",
    "REGENERATION": "💊",
}

_LOG_TYPE_RU = {
    "all": "Все",
    "upgrades": "Прокачка",
    "attacks": "Атаки",
    "purchases": "Покупки",
}


def _fmt_player_card(data: dict) -> str:
    """Format a full player card as HTML."""
    u = data["user"]
    v = data.get("virus", {})
    im = data.get("immunity", {})

    uname = f"@{escape(u['username'])}" if u["username"] else str(u["tg_id"])
    created = u["created_at"].strftime("%d.%m.%Y") if u.get("created_at") else "—"
    last_active = u["last_active"].strftime("%d.%m.%Y %H:%M") if u.get("last_active") else "—"

    lines = [
        f"👤 <b>{uname}</b> (ID: <code>{u['tg_id']}</code>)",
        f"🧫 <b>{u['bio_coins']:,}</b> BioCoins / <b>{u['premium_coins']:,}</b> 💎 PremiumCoins",
    ]

    if v:
        upgrades = v.get("upgrades", {})
        upg_parts = []
        for branch in ("LETHALITY", "CONTAGION", "STEALTH"):
            lvl = upgrades.get(branch, {}).get("level", 0)
            emoji = _BRANCH_EMOJI.get(branch, "")
            upg_parts.append(f"{emoji} {lvl}")
        lines.append(
            f"🦠 Вирус ур.<b>{v.get('level', 1)}</b>"
            f" (атака {v.get('attack_power', 10)},"
            f" заразность {v.get('spread_rate', 1.0):.2f})"
        )
        if upg_parts:
            lines.append("  " + " | ".join(upg_parts))

    if im:
        upgrades = im.get("upgrades", {})
        upg_parts = []
        for branch in ("BARRIER", "DETECTION", "REGENERATION"):
            lvl = upgrades.get(branch, {}).get("level", 0)
            emoji = _BRANCH_EMOJI.get(branch, "")
            upg_parts.append(f"{emoji} {lvl}")
        lines.append(
            f"🛡 Иммунитет ур.<b>{im.get('level', 1)}</b>"
            f" (сопр. {im.get('resistance', 10)})"
        )
        if upg_parts:
            lines.append("  " + " | ".join(upg_parts))

    lines.append(
        f"⚔️ {data['infections_sent_count']} исходящих,"
        f" {data['infections_received_count']} входящих"
    )
    lines.append(f"🏰 {escape(str(data.get('alliance', 'Нет')))}")
    lines.append(f"📅 Регистрация: {created}")
    lines.append(f"🕐 Активность: {last_active}")
    return "\n".join(lines)


def _fmt_promo_list(promos: list[dict]) -> str:
    if not promos:
        return "Промокодов пока нет."
    lines = []
    for p in promos:
        status = "✅" if p["is_active"] and not p["expired"] else "❌"
        limit = f"{p['current_activations']}/{p['max_activations']}" if p["max_activations"] > 0 else f"{p['current_activations']}/∞"
        bio_str = f"+{p['bio_coins']:,} 🧫" if p["bio_coins"] else ""
        prem_str = f"+{p['premium_coins']:,} 💎" if p["premium_coins"] else ""
        reward = " ".join(filter(None, [bio_str, prem_str])) or "—"
        lines.append(f"{status} <b>{escape(p['code'])}</b> ({limit}) {reward}")
    return "\n".join(lines)


def _fmt_promo_detail(info: dict) -> str:
    status = "✅ Активен" if info["is_active"] and not info["expired"] else "❌ Неактивен"
    if info["expired"] and info["is_active"]:
        status = "⏰ Истёк"
    limit = (
        f"{info['current_activations']}/{info['max_activations']}"
        if info["max_activations"] > 0
        else f"{info['current_activations']}/∞"
    )
    expires_str = info["expires_at"].strftime("%d.%m.%Y %H:%M") if info["expires_at"] else "бессрочно"
    created_str = info["created_at"].strftime("%d.%m.%Y %H:%M") if info["created_at"] else "—"

    lines = [
        f"📋 Промокод <b>{escape(info['code'])}</b>",
        f"Статус: {status}",
        f"🧫 BioCoins: {info['bio_coins']:,} | 💎 PremiumCoins: {info['premium_coins']:,}",
        f"Активаций: {limit}",
        f"Действует до: {expires_str}",
        f"Создан: {created_str}",
    ]
    if info["activations"]:
        lines.append("\n<b>Последние активации:</b>")
        for act in info["activations"][:10]:
            uname = f"@{escape(act['username'])}"
            dt = act["activated_at"].strftime("%d.%m %H:%M")
            lines.append(f"  • {uname} — {dt}")
    else:
        lines.append("\nЕщё никто не активировал.")
    return "\n".join(lines)


def _fmt_logs(entries: list[dict], log_type: str, user_id: int) -> str:
    type_label = _LOG_TYPE_RU.get(log_type, log_type)
    if not entries:
        return f"📋 <b>Логи ({type_label})</b>\n\nНет записей."

    lines = [f"📋 <b>Логи ({type_label}) — ID {user_id}</b>\n"]
    for entry in entries[:20]:
        dt = entry["date"].strftime("%d.%m %H:%M") if entry.get("date") else "—"
        if entry["type"] == "transaction":
            amount = entry["amount"]
            sign = "+" if amount >= 0 else ""
            cur = "🧫" if "BIO" in entry["currency"] else "💎"
            reason = entry["subtype"]
            reason_emoji = {
                "MINING": "⛏",
                "UPGRADE": "⬆️",
                "DONATION": "💵",
                "DAILY_BONUS": "🎁",
                "INFECTION_INCOME": "🦠",
                "INFECTION_LOSS": "💀",
            }.get(reason, "📌")
            lines.append(f"[{dt}] {reason_emoji} {sign}{amount:,} {cur}")
        elif entry["type"] == "infection":
            direction = entry["direction"]
            other = escape(entry["other"])
            active_icon = "✅" if entry["active"] else "🏁"
            dmg = entry["damage"]
            lines.append(f"[{dt}] {direction} {other} {active_icon} ({dmg:.1f}/тик)")
    return "\n".join(lines)


async def _get_stats(session: AsyncSession) -> str:
    """Compile global statistics text."""
    total_users = (await session.execute(select(func.count(User.tg_id)))).scalar_one()
    active_infections = (
        await session.execute(
            select(func.count(Infection.id)).where(Infection.is_active == True)  # noqa: E712
        )
    ).scalar_one()
    total_alliances = (await session.execute(select(func.count(Alliance.id)))).scalar_one()

    bio_in_circulation = (
        await session.execute(select(func.sum(User.bio_coins)))
    ).scalar_one() or 0

    total_promos = (
        await session.execute(select(func.count(PromoCode.id)).where(PromoCode.is_active == True))  # noqa: E712
    ).scalar_one()

    return (
        "📊 <b>Статистика BioWars</b>\n\n"
        f"👥 Игроков: <b>{total_users:,}</b>\n"
        f"🦠 Активных заражений: <b>{active_infections:,}</b>\n"
        f"🏰 Альянсов: <b>{total_alliances:,}</b>\n"
        f"🧫 BioCoins в обороте: <b>{bio_in_circulation:,}</b>\n"
        f"📋 Активных промокодов: <b>{total_promos:,}</b>"
    )


# ---------------------------------------------------------------------------
# /promo — for ALL players
# ---------------------------------------------------------------------------


@router.message(Command("promo"))
async def cmd_promo(message: Message, session: AsyncSession) -> None:
    """Activate a promo code. Available to all players."""
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "❓ Использование: <code>/promo КОД</code>\n"
            "Пример: <code>/promo WELCOME</code>",
            parse_mode="HTML",
        )
        return

    code = parts[1].strip()
    ok, msg = await activate_promo(session, message.from_user.id, code)
    await message.answer(msg, parse_mode="HTML")


# ---------------------------------------------------------------------------
# Admin check guard
# ---------------------------------------------------------------------------


async def _deny(message: Message | None, callback: CallbackQuery | None = None) -> None:
    text = "⛔ Доступ запрещён. Эта команда только для администраторов."
    if message:
        await message.answer(text)
    elif callback:
        await callback.answer(text, show_alert=True)


# ---------------------------------------------------------------------------
# /admin and "admin"/"админ" text — main menu
# ---------------------------------------------------------------------------


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        await _deny(message)
        return
    await message.answer(
        "⚙️ <b>Админ-панель</b>\n\n"
        "Добро пожаловать в панель управления BioWars.\n"
        "Выберите раздел:",
        reply_markup=admin_menu_kb(),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_menu")
async def cb_admin_menu(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(None, callback)
        return
    await callback.message.edit_text(
        "⚙️ <b>Админ-панель</b>\n\n"
        "Добро пожаловать в панель управления BioWars.\n"
        "Выберите раздел:",
        reply_markup=admin_menu_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Promo management — admin only
# ---------------------------------------------------------------------------


@router.message(Command("promo_create"))
async def cmd_promo_create(message: Message, session: AsyncSession) -> None:
    """
    /promo_create {code} {bio} {premium} {max_activations} [hours]
    Example: /promo_create WELCOME 500 0 100
    """
    if not _is_admin(message.from_user.id):
        await _deny(message)
        return

    parts = (message.text or "").split()
    # parts[0] = /promo_create
    if len(parts) < 5:
        await message.answer(
            "❓ Использование:\n"
            "<code>/promo_create КОД БИО ПРЕМИУМ МАКС [ЧАСЫ]</code>\n\n"
            "Примеры:\n"
            "<code>/promo_create WELCOME 500 0 100</code>\n"
            "→ +500 bio, 100 активаций, бессрочно\n\n"
            "<code>/promo_create VIP 0 100 10 48</code>\n"
            "→ +100 premium, 10 активаций, 48ч",
            parse_mode="HTML",
        )
        return

    try:
        code = parts[1]
        bio = int(parts[2])
        premium = int(parts[3])
        max_act = int(parts[4])
        hours = int(parts[5]) if len(parts) >= 6 else None
    except ValueError:
        await message.answer("❌ Неверный формат. bio, premium, max_activations и hours — целые числа.")
        return

    ok, msg = await create_promo(
        session,
        code=code,
        bio_coins=bio,
        premium_coins=premium,
        max_activations=max_act,
        created_by=message.from_user.id,
        expires_hours=hours,
    )
    await message.answer(msg, parse_mode="HTML")


@router.message(Command("promo_delete"))
async def cmd_promo_delete(message: Message, session: AsyncSession) -> None:
    """/promo_delete {code}"""
    if not _is_admin(message.from_user.id):
        await _deny(message)
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❓ Использование: <code>/promo_delete КОД</code>", parse_mode="HTML")
        return

    ok, msg = await delete_promo(session, parts[1].strip())
    await message.answer(msg, parse_mode="HTML")


@router.message(Command("promo_list"))
async def cmd_promo_list(message: Message, session: AsyncSession) -> None:
    """/promo_list — show all promo codes."""
    if not _is_admin(message.from_user.id):
        await _deny(message)
        return

    promos = await list_promos(session)
    text = (
        "📋 <b>Управление промокодами</b>\n"
        f"Активных: {sum(1 for p in promos if p['is_active'] and not p['expired'])}\n\n"
        "Создание:\n"
        "<code>/promo_create КОД БИО ПРЕМИУМ МАКС [ЧАСЫ]</code>\n\n"
        "Примеры:\n"
        "<code>/promo_create WELCOME 500 0 100</code>\n"
        "→ +500 bio, 100 активаций, бессрочно\n\n"
        "<code>/promo_create VIP 0 100 10 48</code>\n"
        "→ +100 premium, 10 активаций, 48ч\n\n"
        "<b>Текущие промокоды:</b>\n"
        + _fmt_promo_list(promos)
    )
    await message.answer(text, reply_markup=admin_promos_kb(promos), parse_mode="HTML")


@router.message(Command("promo_info"))
async def cmd_promo_info(message: Message, session: AsyncSession) -> None:
    """/promo_info {code}"""
    if not _is_admin(message.from_user.id):
        await _deny(message)
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❓ Использование: <code>/promo_info КОД</code>", parse_mode="HTML")
        return

    info = await get_promo_info(session, parts[1].strip())
    if info is None:
        await message.answer("❌ Промокод не найден.", parse_mode="HTML")
        return

    await message.answer(
        _fmt_promo_detail(info),
        reply_markup=admin_promo_detail_kb(info["code"], info["is_active"] and not info["expired"]),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Player commands
# ---------------------------------------------------------------------------


@router.message(Command("player"))
async def cmd_player(message: Message, session: AsyncSession) -> None:
    """/player {id_or_username}"""
    if not _is_admin(message.from_user.id):
        await _deny(message)
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "❓ Использование: <code>/player @username</code> или <code>/player ID</code>",
            parse_mode="HTML",
        )
        return

    data = await lookup_player(session, parts[1].strip())
    if data is None:
        await message.answer("❌ Игрок не найден.")
        return

    await message.answer(
        _fmt_player_card(data),
        reply_markup=admin_player_kb(data["user"]["tg_id"]),
        parse_mode="HTML",
    )


@router.message(Command("player_logs"))
async def cmd_player_logs(message: Message, session: AsyncSession) -> None:
    """/player_logs {id_or_username} [type]"""
    if not _is_admin(message.from_user.id):
        await _deny(message)
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer(
            "❓ Использование: <code>/player_logs @user [all|upgrades|attacks|purchases]</code>",
            parse_mode="HTML",
        )
        return

    identifier = parts[1]
    log_type = parts[2] if len(parts) >= 3 else "all"
    if log_type not in ("all", "upgrades", "attacks", "purchases"):
        log_type = "all"

    data = await lookup_player(session, identifier)
    if data is None:
        await message.answer("❌ Игрок не найден.")
        return

    user_id = data["user"]["tg_id"]
    entries = await get_player_logs(session, user_id, log_type)
    text = _fmt_logs(entries, log_type, user_id)
    await message.answer(text, reply_markup=admin_logs_kb(user_id, log_type), parse_mode="HTML")


@router.message(Command("give"))
async def cmd_give(message: Message, session: AsyncSession) -> None:
    """/give {id_or_username} {bio} {premium}"""
    if not _is_admin(message.from_user.id):
        await _deny(message)
        return

    parts = (message.text or "").split()
    if len(parts) < 4:
        await message.answer(
            "❓ Использование: <code>/give @user БИО ПРЕМИУМ</code>\n"
            "Пример: <code>/give @MrKatleta 1000 50</code>",
            parse_mode="HTML",
        )
        return

    identifier = parts[1]
    try:
        bio = int(parts[2])
        premium = int(parts[3])
    except ValueError:
        await message.answer("❌ bio и premium должны быть целыми числами.")
        return

    data = await lookup_player(session, identifier)
    if data is None:
        await message.answer("❌ Игрок не найден.")
        return

    ok, msg = await give_currency(session, data["user"]["tg_id"], bio, premium)
    await message.answer(msg, parse_mode="HTML")


@router.message(Command("setbalance"))
async def cmd_setbalance(message: Message, session: AsyncSession) -> None:
    """/setbalance {id_or_username} {bio} {premium}"""
    if not _is_admin(message.from_user.id):
        await _deny(message)
        return

    parts = (message.text or "").split()
    if len(parts) < 4:
        await message.answer(
            "❓ Использование: <code>/setbalance @user БИО ПРЕМИУМ</code>\n"
            "Пример: <code>/setbalance @MrKatleta 5000 200</code>",
            parse_mode="HTML",
        )
        return

    identifier = parts[1]
    try:
        bio = int(parts[2])
        premium = int(parts[3])
    except ValueError:
        await message.answer("❌ bio и premium должны быть целыми числами.")
        return

    data = await lookup_player(session, identifier)
    if data is None:
        await message.answer("❌ Игрок не найден.")
        return

    ok, msg = await set_balance(session, data["user"]["tg_id"], bio, premium)
    await message.answer(msg, parse_mode="HTML")


# ---------------------------------------------------------------------------
# Stats callback
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(None, callback)
        return

    text = await _get_stats(session)
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="admin_menu")
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="HTML")
    await callback.answer()


# ---------------------------------------------------------------------------
# Promo callbacks
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "admin_promos")
async def cb_admin_promos(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(None, callback)
        return

    promos = await list_promos(session)
    active_count = sum(1 for p in promos if p["is_active"] and not p["expired"])
    text = (
        "📋 <b>Управление промокодами</b>\n"
        f"Активных: <b>{active_count}</b>\n\n"
        "Создание:\n"
        "<code>/promo_create КОД БИО ПРЕМИУМ МАКС [ЧАСЫ]</code>\n\n"
        "Примеры:\n"
        "<code>/promo_create WELCOME 500 0 100</code>\n"
        "→ +500 bio, 100 активаций, бессрочно\n\n"
        "<code>/promo_create VIP 0 100 10 48</code>\n"
        "→ +100 premium, 10 активаций, 48ч\n\n"
        "<b>Текущие промокоды:</b>\n"
        + _fmt_promo_list(promos)
    )
    await callback.message.edit_text(
        text,
        reply_markup=admin_promos_kb(promos),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_promo_info_"))
async def cb_promo_info(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(None, callback)
        return

    code = callback.data.removeprefix("admin_promo_info_")
    info = await get_promo_info(session, code)
    if info is None:
        await callback.answer("Промокод не найден.", show_alert=True)
        return

    await callback.message.edit_text(
        _fmt_promo_detail(info),
        reply_markup=admin_promo_detail_kb(info["code"], info["is_active"] and not info["expired"]),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_promo_del_"))
async def cb_promo_del(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(None, callback)
        return

    code = callback.data.removeprefix("admin_promo_del_")
    ok, msg = await delete_promo(session, code)
    await callback.answer(msg[:200], show_alert=True)

    # Refresh promo list
    promos = await list_promos(session)
    active_count = sum(1 for p in promos if p["is_active"] and not p["expired"])
    text = (
        "📋 <b>Управление промокодами</b>\n"
        f"Активных: <b>{active_count}</b>\n\n"
        "<b>Текущие промокоды:</b>\n"
        + _fmt_promo_list(promos)
    )
    await callback.message.edit_text(
        text,
        reply_markup=admin_promos_kb(promos),
        parse_mode="HTML",
    )


@router.callback_query(F.data == "admin_promo_help")
async def cb_promo_help(callback: CallbackQuery) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(None, callback)
        return
    await callback.answer(
        "Используйте команду:\n/promo_create КОД БИО ПРЕМИУМ МАКС [ЧАСЫ]",
        show_alert=True,
    )


# ---------------------------------------------------------------------------
# Player search — FSM
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "admin_find_player")
async def cb_find_player(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(None, callback)
        return

    await state.set_state(AdminFindPlayer.waiting_for_identifier)
    await callback.message.edit_text(
        "🔍 <b>Найти игрока</b>\n\n"
        "Отправьте @username или Telegram ID:\n"
        "Примеры: <code>@MrKatleta</code> или <code>1686189086</code>",
        reply_markup=cancel_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminFindPlayer.waiting_for_identifier)
async def fsm_find_player_input(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    await state.clear()
    identifier = (message.text or "").strip()

    data = await lookup_player(session, identifier)
    if data is None:
        await message.answer(
            "❌ Игрок не найден. Проверь @username или ID.",
            reply_markup=cancel_kb(),
            parse_mode="HTML",
        )
        return

    await message.answer(
        _fmt_player_card(data),
        reply_markup=admin_player_kb(data["user"]["tg_id"]),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Player profile callback
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("admin_player_"))
async def cb_player_profile(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(None, callback)
        return

    try:
        user_id = int(callback.data.removeprefix("admin_player_"))
    except ValueError:
        await callback.answer("Неверный ID.", show_alert=True)
        return

    data = await lookup_player(session, str(user_id))
    if data is None:
        await callback.answer("Игрок не найден.", show_alert=True)
        return

    await callback.message.edit_text(
        _fmt_player_card(data),
        reply_markup=admin_player_kb(user_id),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Logs callback
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("admin_logs_"))
async def cb_admin_logs(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(None, callback)
        return

    # Format: admin_logs_{user_id}_{type}
    suffix = callback.data.removeprefix("admin_logs_")
    parts = suffix.rsplit("_", 1)
    if len(parts) != 2:
        await callback.answer("Неверный формат.", show_alert=True)
        return

    try:
        user_id = int(parts[0])
    except ValueError:
        await callback.answer("Неверный ID.", show_alert=True)
        return

    log_type = parts[1]
    if log_type not in ("all", "upgrades", "attacks", "purchases"):
        log_type = "all"

    entries = await get_player_logs(session, user_id, log_type)
    text = _fmt_logs(entries, log_type, user_id)
    await callback.message.edit_text(
        text,
        reply_markup=admin_logs_kb(user_id, log_type),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Give currency — FSM (inline) and callbacks
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "admin_give_start")
async def cb_give_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start give currency FSM from the admin menu."""
    if not _is_admin(callback.from_user.id):
        await _deny(None, callback)
        return

    await state.set_state(AdminGiveCurrency.waiting_for_input)
    await callback.message.edit_text(
        "💰 <b>Выдать валюту</b>\n\n"
        "Отправьте: <code>@username БИО ПРЕМИУМ</code>\n"
        "Пример: <code>@MrKatleta 1000 0</code>\n\n"
        "Чтобы выдать только premium: <code>@MrKatleta 0 50</code>",
        reply_markup=cancel_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(
    F.data.startswith("admin_give_")
    & ~F.data.startswith("admin_give_start")
    & ~F.data.startswith("admin_give_confirm_")
)
async def cb_give_player(callback: CallbackQuery, state: FSMContext) -> None:
    """Start give currency for a specific player (from player card)."""
    if not _is_admin(callback.from_user.id):
        await _deny(None, callback)
        return

    suffix = callback.data.removeprefix("admin_give_")

    try:
        user_id = int(suffix)
    except ValueError:
        await callback.answer("Неверный ID.", show_alert=True)
        return

    await state.set_state(AdminGiveCurrency.waiting_for_input)
    await state.update_data(prefilled_user_id=user_id)
    await callback.message.edit_text(
        f"💰 <b>Выдать валюту — ID {user_id}</b>\n\n"
        "Введите: <code>БИО ПРЕМИУМ</code>\n"
        "Пример: <code>1000 50</code>",
        reply_markup=cancel_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminGiveCurrency.waiting_for_input)
async def fsm_give_input(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    fsm_data = await state.get_data()
    prefilled_user_id: int | None = fsm_data.get("prefilled_user_id")
    await state.clear()

    parts = (message.text or "").strip().split()

    if prefilled_user_id:
        # Input is just "bio premium"
        if len(parts) < 2:
            await message.answer("❌ Формат: <code>БИО ПРЕМИУМ</code>", parse_mode="HTML")
            return
        identifier = str(prefilled_user_id)
        bio_str, prem_str = parts[0], parts[1]
    else:
        # Input is "@user bio premium"
        if len(parts) < 3:
            await message.answer(
                "❌ Формат: <code>@username БИО ПРЕМИУМ</code>", parse_mode="HTML"
            )
            return
        identifier, bio_str, prem_str = parts[0], parts[1], parts[2]

    try:
        bio = int(bio_str)
        premium = int(prem_str)
    except ValueError:
        await message.answer("❌ bio и premium должны быть целыми числами.")
        return

    data = await lookup_player(session, identifier)
    if data is None:
        await message.answer("❌ Игрок не найден.")
        return

    user_id = data["user"]["tg_id"]
    uname = f"@{data['user']['username']}" if data["user"]["username"] else str(user_id)

    await message.answer(
        f"Выдать <b>{uname}</b>:\n"
        f"🧫 {bio:,} BioCoins и 💎 {premium:,} PremiumCoins?",
        reply_markup=confirm_give_kb(user_id, bio, premium),
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("admin_give_confirm_"))
async def cb_give_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(None, callback)
        return

    # Format: admin_give_confirm_{user_id}_{bio}_{premium}
    suffix = callback.data.removeprefix("admin_give_confirm_")
    parts = suffix.split("_")
    if len(parts) != 3:
        await callback.answer("Неверный формат.", show_alert=True)
        return

    try:
        user_id = int(parts[0])
        bio = int(parts[1])
        premium = int(parts[2])
    except ValueError:
        await callback.answer("Неверный формат.", show_alert=True)
        return

    ok, msg = await give_currency(session, user_id, bio, premium)
    await callback.message.edit_text(msg, parse_mode="HTML")
    await callback.answer("✅ Готово!" if ok else "❌ Ошибка")


# ---------------------------------------------------------------------------
# Set balance callback
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("admin_setbal_"))
async def cb_setbal(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await _deny(None, callback)
        return

    suffix = callback.data.removeprefix("admin_setbal_")
    try:
        user_id = int(suffix)
    except ValueError:
        await callback.answer("Неверный ID.", show_alert=True)
        return

    await state.set_state(AdminSetBalance.waiting_for_input)
    await state.update_data(target_user_id=user_id)
    await callback.message.edit_text(
        f"⚙️ <b>Установить баланс — ID {user_id}</b>\n\n"
        "Введите: <code>БИО ПРЕМИУМ</code>\n"
        "Пример: <code>5000 200</code>",
        reply_markup=cancel_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AdminSetBalance.waiting_for_input)
async def fsm_setbal_input(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        await state.clear()
        return

    fsm_data = await state.get_data()
    target_user_id: int = fsm_data.get("target_user_id")
    await state.clear()

    parts = (message.text or "").strip().split()
    if len(parts) < 2:
        await message.answer("❌ Формат: <code>БИО ПРЕМИУМ</code>", parse_mode="HTML")
        return

    try:
        bio = int(parts[0])
        premium = int(parts[1])
    except ValueError:
        await message.answer("❌ bio и premium должны быть целыми числами.")
        return

    ok, msg = await set_balance(session, target_user_id, bio, premium)
    await message.answer(msg, parse_mode="HTML")


# ---------------------------------------------------------------------------
# Cancel FSM
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "admin_cancel")
async def cb_admin_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        "⚙️ <b>Админ-панель</b>\n\n"
        "Добро пожаловать в панель управления BioWars.\n"
        "Выберите раздел:",
        reply_markup=admin_menu_kb(),
        parse_mode="HTML",
    )
    await callback.answer("Отменено.")


# ---------------------------------------------------------------------------
# Events management — callbacks
# ---------------------------------------------------------------------------


def _fmt_events_admin(events: list) -> str:
    """Format active events list for admin panel."""
    now = datetime.now(UTC).replace(tzinfo=None)
    text = "🌍 <b>Управление ивентами</b>\n\n"
    if events:
        text += "<b>Активные ивенты:</b>\n"
        for e in events:
            emoji = EVENT_EMOJI.get(e.event_type, "🌍")
            delta = (e.ends_at - now).total_seconds()
            remaining_h = max(0, delta / 3600)
            text += f"{emoji} {escape(e.title)} — ещё {remaining_h:.0f}ч\n"
    else:
        text += "Нет активных ивентов."
    return text


@router.callback_query(F.data == "admin_events")
async def cb_admin_events(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show event management menu."""
    if not _is_admin(callback.from_user.id):
        await _deny(None, callback)
        return

    events = await get_active_events(session)
    await callback.message.edit_text(
        _fmt_events_admin(events),
        reply_markup=admin_events_kb(events),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "admin_event_types")
async def cb_admin_event_types(callback: CallbackQuery) -> None:
    """Show event type selection."""
    if not _is_admin(callback.from_user.id):
        await _deny(None, callback)
        return

    await callback.message.edit_text(
        "🌍 <b>Выберите тип ивента</b>",
        reply_markup=admin_event_types_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_evt_create:"))
async def cb_admin_evt_create(callback: CallbackQuery) -> None:
    """Show duration selection for the chosen event type."""
    if not _is_admin(callback.from_user.id):
        await _deny(None, callback)
        return

    event_type_str = callback.data.removeprefix("admin_evt_create:")
    # Validate that the type is known
    try:
        et = EventType(event_type_str)
    except ValueError:
        await callback.answer("Неизвестный тип ивента.", show_alert=True)
        return

    emoji = EVENT_EMOJI.get(et, "🌍")
    name = EVENT_NAMES.get(et, event_type_str)

    descriptions = {
        EventType.GOLD_RUSH: (
            "Все игроки получают <b>x2 к добыче</b> ресурсов и ежедневному бонусу.\n"
            "Отличное время для накопления 🧫 BioCoins!"
        ),
        EventType.ARMS_RACE: (
            "Стоимость прокачки <b>снижена на 50%</b> для всех веток.\n"
            "Идеальный момент для массовых улучшений!"
        ),
        EventType.PLAGUE_SEASON: (
            "Шанс успешного заражения <b>увеличен на 50%</b> для всех.\n"
            "Агрессивные игроки получат преимущество — осторожно!"
        ),
        EventType.IMMUNITY_WAVE: (
            "Защита всех игроков <b>усилена на 50%</b>.\n"
            "Хорошее время для безопасной добычи и прокачки."
        ),
        EventType.MUTATION_STORM: (
            "Шанс получить мутацию <b>увеличен в 3 раза</b>.\n"
            "Атакуйте чаще — мутации сыпятся как из рога изобилия!"
        ),
        EventType.CEASEFIRE: (
            "Все атаки <b>запрещены</b> на время ивента.\n"
            "Мирное время: добывайте, качайтесь, торгуйте."
        ),
        EventType.PANDEMIC: (
            "Появляется <b>босс-вирус</b> с огромным запасом HP.\n"
            "Все игроки объединяются чтобы его уничтожить.\n"
            "Топ-5 по урону получают призы: 🧫, 💎 и редкие мутации!"
        ),
    }
    desc = descriptions.get(et, "")

    # Призы за топ-5
    prizes = (
        "\n<b>🏆 Призы за топ-5:</b>\n"
        "🥇 2000 🧫 + 50 💎 + 🟣 мутация\n"
        "🥈 1500 🧫 + 30 💎 + 🔵 мутация\n"
        "🥉 1000 🧫 + 20 💎 + 🔵 мутация\n"
        "4. 500 🧫 + 10 💎 + 🟢 мутация\n"
        "5. 300 🧫 + 5 💎 + 🟢 мутация"
    ) if et == EventType.PANDEMIC else (
        "\n<b>🏆 Призы за топ-5 (по активности):</b>\n"
        "🥇 1000 🧫 + 25 💎\n"
        "🥈 700 🧫 + 15 💎\n"
        "🥉 500 🧫 + 10 💎\n"
        "4. 300 🧫 + 5 💎\n"
        "5. 200 🧫"
    )

    await callback.message.edit_text(
        f"🌍 <b>Создать ивент: {emoji} {name}</b>\n\n"
        f"{desc}\n"
        f"{prizes}\n\n"
        "⏱ <b>Выберите длительность:</b>",
        reply_markup=admin_event_duration_kb(event_type_str),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_evt_dur:"))
async def cb_admin_evt_dur(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Handle duration selection.

    For PANDEMIC: show HP selection screen.
    For all others: create the event immediately.
    """
    if not _is_admin(callback.from_user.id):
        await _deny(None, callback)
        return

    # Format: admin_evt_dur:{type}:{hours}
    parts = callback.data.removeprefix("admin_evt_dur:").split(":")
    if len(parts) != 2:
        await callback.answer("Неверный формат.", show_alert=True)
        return

    event_type_str, hours_str = parts
    try:
        et = EventType(event_type_str)
        duration = int(hours_str)
    except (ValueError, KeyError):
        await callback.answer("Неверные параметры.", show_alert=True)
        return

    # Pandemic needs extra step — boss HP selection
    if et == EventType.PANDEMIC:
        emoji = EVENT_EMOJI[et]
        name = EVENT_NAMES[et]
        await callback.message.edit_text(
            f"💀 <b>Пандемия — выберите HP босса</b>\n\n"
            f"Длительность: <b>{duration}ч</b>",
            reply_markup=admin_pandemic_hp_kb(duration),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    # Create non-pandemic event
    emoji = EVENT_EMOJI.get(et, "🌍")
    name = EVENT_NAMES.get(et, et.value)
    description = f"Активное событие: {name}."
    event = await create_event(
        session=session,
        event_type=et,
        title=name,
        description=description,
        duration_hours=duration,
        created_by=callback.from_user.id,
    )

    ends_str = event.ends_at.strftime("%d.%m.%Y %H:%M")
    await callback.message.edit_text(
        f"✅ <b>Ивент создан!</b>\n\n"
        f"{emoji} {name}\n"
        f"⏱ Длительность: {duration} ч\n"
        f"📅 До: {ends_str} UTC",
        reply_markup=admin_event_detail_kb(event.id),
        parse_mode="HTML",
    )
    await callback.answer("✅ Ивент запущен!")


@router.callback_query(F.data.startswith("admin_pandemic:"))
async def cb_admin_pandemic(callback: CallbackQuery, session: AsyncSession) -> None:
    """Create pandemic event with chosen duration and boss HP."""
    if not _is_admin(callback.from_user.id):
        await _deny(None, callback)
        return

    # Format: admin_pandemic:{duration}:{boss_hp}
    parts = callback.data.removeprefix("admin_pandemic:").split(":")
    if len(parts) != 2:
        await callback.answer("Неверный формат.", show_alert=True)
        return

    try:
        duration = int(parts[0])
        boss_hp = int(parts[1])
    except ValueError:
        await callback.answer("Неверные параметры.", show_alert=True)
        return

    event = await start_pandemic(
        session=session,
        boss_hp=boss_hp,
        duration_hours=duration,
        created_by=callback.from_user.id,
    )

    ends_str = event.ends_at.strftime("%d.%m.%Y %H:%M")
    await callback.message.edit_text(
        f"✅ <b>Ивент создан!</b>\n\n"
        f"💀 Пандемия — Босс-вирус\n"
        f"💀 HP босса: {boss_hp:,}\n"
        f"⏱ Длительность: {duration} ч\n"
        f"📅 До: {ends_str} UTC",
        reply_markup=admin_event_detail_kb(event.id),
        parse_mode="HTML",
    )
    await callback.answer("✅ Пандемия запущена!")


@router.callback_query(F.data.startswith("admin_evt_detail:"))
async def cb_admin_evt_detail(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show details for a specific active event."""
    if not _is_admin(callback.from_user.id):
        await _deny(None, callback)
        return

    try:
        event_id = int(callback.data.removeprefix("admin_evt_detail:"))
    except ValueError:
        await callback.answer("Неверный ID.", show_alert=True)
        return

    event = await get_event_by_id(session, event_id)
    if event is None or not event.is_active:
        await callback.answer("Ивент не найден или уже завершён.", show_alert=True)
        events = await get_active_events(session)
        await callback.message.edit_text(
            _fmt_events_admin(events),
            reply_markup=admin_events_kb(events),
            parse_mode="HTML",
        )
        return

    now = datetime.now(UTC).replace(tzinfo=None)
    emoji = EVENT_EMOJI.get(event.event_type, "🌍")
    name = EVENT_NAMES.get(event.event_type, event.event_type.value)
    delta = max(0, (event.ends_at - now).total_seconds())
    remaining_h = delta / 3600
    ends_str = event.ends_at.strftime("%d.%m.%Y %H:%M")
    text = (
        f"{emoji} <b>{escape(event.title)}</b>\n\n"
        f"Тип: <b>{name}</b>\n"
        f"ID: <code>{event.id}</code>\n"
        f"⏳ Осталось: <b>{remaining_h:.1f}ч</b>\n"
        f"📅 До: {ends_str} UTC"
    )
    await callback.message.edit_text(
        text,
        reply_markup=admin_event_detail_kb(event_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_evt_stop_ask:"))
async def cb_admin_evt_stop_ask(callback: CallbackQuery, session: AsyncSession) -> None:
    """Ask for confirmation before stopping an event."""
    if not _is_admin(callback.from_user.id):
        await _deny(None, callback)
        return

    try:
        event_id = int(callback.data.removeprefix("admin_evt_stop_ask:"))
    except ValueError:
        await callback.answer("Неверный ID.", show_alert=True)
        return

    event = await get_event_by_id(session, event_id)
    if event is None or not event.is_active:
        await callback.answer("Ивент уже завершён.", show_alert=True)
        events = await get_active_events(session)
        await callback.message.edit_text(
            _fmt_events_admin(events),
            reply_markup=admin_events_kb(events),
            parse_mode="HTML",
        )
        return

    emoji = EVENT_EMOJI.get(event.event_type, "🌍")
    await callback.message.edit_text(
        f"⚠️ <b>Остановить ивент?</b>\n\n"
        f"{emoji} {escape(event.title)}\n\n"
        "Это действие нельзя отменить.",
        reply_markup=admin_event_stop_confirm_kb(event_id),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_evt_stop:"))
async def cb_admin_evt_stop(callback: CallbackQuery, session: AsyncSession) -> None:
    """Stop an active event after confirmation."""
    if not _is_admin(callback.from_user.id):
        await _deny(None, callback)
        return

    try:
        event_id = int(callback.data.removeprefix("admin_evt_stop:"))
    except ValueError:
        await callback.answer("Неверный ID.", show_alert=True)
        return

    success = await stop_event(session, event_id)

    events = await get_active_events(session)
    if success:
        await callback.answer(f"✅ Ивент #{event_id} остановлен.", show_alert=True)
    else:
        await callback.answer(f"Ивент #{event_id} не найден или уже завершён.", show_alert=True)

    await callback.message.edit_text(
        _fmt_events_admin(events),
        reply_markup=admin_events_kb(events),
        parse_mode="HTML",
    )
