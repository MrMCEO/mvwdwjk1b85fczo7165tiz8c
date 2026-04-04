"""
Profile handlers — player profile view, attack log, transaction log, display name.
"""

from __future__ import annotations

from datetime import UTC, datetime

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.profile import log_pagination_kb, profile_kb
from bot.services.activity import get_attack_log, get_transaction_log
from bot.services.player import get_player_profile
from bot.services.premium import clear_display_name, format_username, set_display_name
from bot.utils.emoji import render_virus_name


def _is_premium_active(premium_until: datetime | None) -> bool:
    """Return True if premium_until is in the future (naive UTC comparison)."""
    if premium_until is None:
        return False
    now = datetime.now(UTC).replace(tzinfo=None)
    return premium_until > now


class DisplayNameStates(StatesGroup):
    waiting_for_name = State()


router = Router(name="profile")

# Items per page in log views
PAGE_SIZE = 10


# ---------------------------------------------------------------------------
# Helper formatters
# ---------------------------------------------------------------------------


def _fmt_profile(data: dict) -> str:
    """Format a player profile dict into HTML text."""
    if "error" in data:
        return f"❌ {data['error']}"

    u = data["user"]
    v = data.get("virus") or {}
    im = data.get("immunity") or {}

    premium_active = _is_premium_active(u.get("premium_until"))
    base_username = f"@{u['username']}" if u.get("username") else f"id{u['tg_id']}"
    username_display = format_username(
        base_username,
        u.get("premium_prefix"),
        premium_active,
        display_name=u.get("display_name"),
    )

    virus_name = render_virus_name(v.get("name", "—"), v.get("name_entities_json"))
    virus_level = v.get("level", "—")
    immunity_level = im.get("level", "—")

    sent = data.get("infections_sent_count", 0)
    received = data.get("infections_received_count", 0)

    lines = [
        f"📊 <b>Профиль игрока {username_display}</b>\n",
        f"🦠 Вирус: <b>{virus_name}</b> (ур. <b>{virus_level}</b>)",
        f"🛡 Иммунитет: ур. <b>{immunity_level}</b>",
        f"💰 Баланс: <b>{u['bio_coins']:,}</b> 🧫",
    ]

    if u.get("premium_coins", 0) > 0:
        lines.append(f"💎 PremiumCoins: <b>{u['premium_coins']:,}</b>")

    if premium_active:
        until_str = u["premium_until"].strftime("%d.%m.%Y")
        lines.append(f"⭐ Премиум до: <b>{until_str}</b>")

    lines.append("")
    lines.append(f"⚔️ Активных атак исходящих: <b>{sent}</b>")
    lines.append(f"🎯 Активных атак входящих: <b>{received}</b>")

    return "\n".join(lines)


def _fmt_attack_log_page(entries: list[dict], page: int) -> str:
    """Format a single page of attack log entries."""
    if not entries:
        return "📋 <b>Лог атак</b>\n\nПока нет ни одной атаки."

    start = page * PAGE_SIZE
    page_entries = entries[start : start + PAGE_SIZE]

    if not page_entries:
        return "📋 <b>Лог атак</b>\n\nНа этой странице нет записей."

    lines = [f"📋 <b>Лог атак</b> (стр. {page + 1})\n"]
    for e in page_entries:
        direction = "➡️ Атаковал" if e["type"] == "sent" else "⬅️ Атакован"
        opp = f"@{e['opponent_username']}" if e["opponent_username"] else "???"
        status = "🟢 активно" if e["is_active"] else "⚫️ завершено"
        dt = e["started_at"].strftime("%d.%m %H:%M") if e["started_at"] else "—"
        lines.append(
            f"{direction} {opp}\n"
            f"    📅 {dt} | {status} | 💔 {e['damage_per_tick']:.1f}/тик"
        )

    return "\n\n".join(lines)


def _fmt_transaction_log_page(entries: list[dict], page: int) -> str:
    """Format a single page of transaction log entries."""
    if not entries:
        return "💰 <b>История транзакций</b>\n\nТранзакций пока нет."

    start = page * PAGE_SIZE
    page_entries = entries[start : start + PAGE_SIZE]

    if not page_entries:
        return "💰 <b>История транзакций</b>\n\nНа этой странице нет записей."

    lines = [f"💰 <b>История транзакций</b> (стр. {page + 1})\n"]
    for e in page_entries:
        sign = "+" if e["amount"] >= 0 else ""
        dt = e["created_at"].strftime("%d.%m %H:%M") if e["created_at"] else "—"
        lines.append(
            f"{e['reason']}\n"
            f"    {sign}{e['amount']} {e['currency']} | 📅 {dt}"
        )

    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# Profile main view
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "profile")
async def cb_profile(callback: CallbackQuery, session: AsyncSession) -> None:
    user_id = callback.from_user.id
    data = await get_player_profile(session, user_id)
    text = _fmt_profile(data)

    await callback.message.edit_text(
        text,
        reply_markup=profile_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Attack log (paginated)
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data and c.data.startswith("attack_log:"))
async def cb_attack_log(callback: CallbackQuery, session: AsyncSession) -> None:
    _, raw_page = callback.data.split(":", 1)
    try:
        page = int(raw_page)
    except ValueError:
        page = 0
    page = max(0, page)

    user_id = callback.from_user.id

    # Fetch enough entries to detect if there's a next page
    fetch_limit = (page + 2) * PAGE_SIZE  # always fetch one extra page worth
    entries = await get_attack_log(session, user_id, limit=fetch_limit)

    has_next = len(entries) > (page + 1) * PAGE_SIZE

    text = _fmt_attack_log_page(entries, page)

    await callback.message.edit_text(
        text,
        reply_markup=log_pagination_kb("attack_log", page, has_next),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Transaction log (paginated)
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data and c.data.startswith("transaction_log:"))
async def cb_transaction_log(callback: CallbackQuery, session: AsyncSession) -> None:
    _, raw_page = callback.data.split(":", 1)
    try:
        page = int(raw_page)
    except ValueError:
        page = 0
    page = max(0, page)

    user_id = callback.from_user.id

    fetch_limit = (page + 2) * PAGE_SIZE
    entries = await get_transaction_log(session, user_id, limit=fetch_limit)

    has_next = len(entries) > (page + 1) * PAGE_SIZE

    text = _fmt_transaction_log_page(entries, page)

    await callback.message.edit_text(
        text,
        reply_markup=log_pagination_kb("transaction_log", page, has_next),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Display name — установка и сброс
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "set_display_name")
async def cb_set_display_name(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Запросить у пользователя новое отображаемое имя."""
    await state.set_state(DisplayNameStates.waiting_for_name)
    await callback.message.edit_text(
        "✏️ <b>Изменить отображаемое имя</b>\n\n"
        "Введи новое имя (до 20 символов).\n"
        "Оно будет показываться вместо твоего @username везде в игре.\n\n"
        "Отправь <code>/cancel</code> для отмены.",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(DisplayNameStates.waiting_for_name)
async def msg_display_name_input(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Обработать ввод нового отображаемого имени."""
    text = (message.text or "").strip()

    # Отмена
    if text.lower() in ("/cancel", "отмена"):
        await state.clear()
        await message.answer(
            "❌ Изменение имени отменено.",
            parse_mode="HTML",
        )
        return

    ok, msg = await set_display_name(session, message.from_user.id, text)
    await state.clear()
    await message.answer(msg, parse_mode="HTML")


@router.callback_query(lambda c: c.data == "clear_display_name")
async def cb_clear_display_name(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Сбросить кастомное отображаемое имя на @username."""
    ok, msg = await clear_display_name(session, callback.from_user.id)
    await callback.answer(msg, show_alert=True)
