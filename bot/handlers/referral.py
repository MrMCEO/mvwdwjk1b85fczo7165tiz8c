"""
Referral program handler.

Commands / text:
  /ref              — show referral menu
  "рефералы" etc.   — same via text_commands router

Callbacks:
  referral_menu            — show referral menu
  referral_claim_menu      — show claimable reward selection
  referral_claim:<n>       — claim reward for level n
  referral_claim_repeatable — claim the infinite repeatable reward
  referral_list            — list of referred users (brief)
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.referral import referral_back_kb, referral_claim_kb, referral_menu_kb
from bot.services.referral import (
    claim_repeatable_reward,
    claim_reward,
    get_referral_link,
    get_referral_stats,
)
from bot.utils.chat import smart_reply

router = Router(name="referral")

# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

_STATUS_ICONS = {
    "BIO_PLUS":   "🟢",
    "BIO_PRO":    "🔵",
    "BIO_LEGEND": "👑",
}

_STATUS_NAMES = {
    "BIO_PLUS":   "Bio+",
    "BIO_PRO":    "Pro",
    "BIO_LEGEND": "Legend",
}


def _fmt_reward_line(reward: dict, active_count: int) -> str:
    """Format a single reward row for the referral menu message."""
    level = reward["level"]
    required = reward["required"]
    bio = reward["bio"]
    premium = reward["premium"]
    status = reward["status"]
    status_days = reward["status_days"]
    is_claimed = reward["is_claimed"]
    is_available = reward["is_available"]

    # Build reward description
    parts = [f"<code>{bio}</code> 🧫"]
    if premium:
        parts.append(f"<code>{premium}</code> 💎")
    if status:
        icon = _STATUS_ICONS.get(status, "⭐")
        name = _STATUS_NAMES.get(status, status)
        days_str = f" {status_days}д" if status_days else " навсегда"
        parts.append(f"{icon} {name}{days_str}")
    reward_desc = " + ".join(parts)

    if is_claimed:
        mark = "✅"
        suffix = "<i>Получено</i>"
    elif is_available:
        mark = "🟡"
        suffix = "<b>Забрать!</b>"
    else:
        mark = "⬜"
        # Show progress only for the next unreached level
        if active_count < required:
            suffix = f"<i>{active_count}/{required}</i>"
        else:
            suffix = ""

    return f"{mark} <b>Ур. {level}</b> (<code>{required}</code> реф) — {reward_desc} {suffix}".strip()


def _fmt_repeatable_line(stats: dict) -> str:
    """Format the infinite repeatable reward row."""
    available = stats["repeatable_available"]
    claimed = stats["repeatable_claimed"]
    bio = stats["repeatable_bio"]
    step = stats["repeatable_step"]
    base = stats["repeatable_base"]
    active = stats["active_count"]

    # Progress toward next claim: how many of the current REPEATABLE_STEP have been used
    if active <= base:
        progress = active  # show plain count until base is reached
        next_at = base + step
        suffix = f"<i>{active}/{next_at}</i>"
        mark = "⬜"
    else:
        beyond = active - base
        progress_in_step = beyond % step
        if available > 0:
            mark = "🟡"
            suffix = f"<b>Доступно: {available}×</b>"
        else:
            mark = "🔄"
            needed = step - progress_in_step
            suffix = f"<i>ещё {needed} реф. до следующей</i>"

    times_str = f" (получено раз: {claimed})" if claimed > 0 else ""
    return (
        f"{mark} <b>∞ Каждые {step} рефералов</b> (сверх {base}) — "
        f"<code>{bio}</code> 🧫{times_str} {suffix}"
    ).strip()


def _fmt_referral_menu(stats: dict, link: str) -> str:
    active = stats["active_count"]
    qualified = stats["qualified_count"]
    total = stats["total_referrals"]

    reward_lines = "\n".join(_fmt_reward_line(r, active) for r in stats["rewards"])
    repeatable_line = _fmt_repeatable_line(stats)

    return (
        "🤝 <b>Реферальная программа</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "🔗 Твоя реферальная ссылка:\n"
        f"<code>{link}</code>\n\n"
        "📊 <b>Статистика</b>\n"
        f"👥 Всего приглашено: <code>{total}</code>\n"
        f"✅ Активных (7 дней): <code>{active}</code>\n"
        f"🏆 Квалифицированных: <code>{qualified}</code>\n\n"
        "🎁 <b>Награды по уровням</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"{reward_lines}\n"
        f"{repeatable_line}"
    )


# ---------------------------------------------------------------------------
# /ref command
# ---------------------------------------------------------------------------


@router.message(Command("ref"))
async def cmd_ref(message: Message, session: AsyncSession) -> None:
    """Show the referral menu."""
    user_id = message.from_user.id
    link = await get_referral_link(user_id)
    stats = await get_referral_stats(session, user_id)
    has_claimable = any(r["is_available"] for r in stats["rewards"])
    has_repeatable = stats["repeatable_available"] > 0
    text = _fmt_referral_menu(stats, link)
    await smart_reply(
        message,
        text,
        reply_markup=referral_menu_kb(has_claimable, has_repeatable),
    )


# ---------------------------------------------------------------------------
# Callback: main referral menu
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "referral_menu")
async def cb_referral_menu(call: CallbackQuery, session: AsyncSession) -> None:
    user_id = call.from_user.id
    link = await get_referral_link(user_id)
    stats = await get_referral_stats(session, user_id)
    has_claimable = any(r["is_available"] for r in stats["rewards"])
    has_repeatable = stats["repeatable_available"] > 0
    text = _fmt_referral_menu(stats, link)
    await call.message.edit_text(
        text,
        reply_markup=referral_menu_kb(has_claimable, has_repeatable),
        parse_mode="HTML",
    )
    await call.answer()


# ---------------------------------------------------------------------------
# Callback: claim selection menu
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "referral_claim_menu")
async def cb_referral_claim_menu(call: CallbackQuery, session: AsyncSession) -> None:
    user_id = call.from_user.id
    stats = await get_referral_stats(session, user_id)
    claimable = [r["level"] for r in stats["rewards"] if r["is_available"]]

    if not claimable:
        await call.answer("Нет доступных наград.", show_alert=True)
        return

    await call.message.edit_text(
        "🎁 <b>Получить награду</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Выбери уровень для получения награды:",
        reply_markup=referral_claim_kb(claimable),
        parse_mode="HTML",
    )
    await call.answer()


# ---------------------------------------------------------------------------
# Callback: claim specific reward
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("referral_claim:"))
async def cb_referral_claim(call: CallbackQuery, session: AsyncSession) -> None:
    user_id = call.from_user.id
    try:
        level = int(call.data.split(":")[1])
    except (IndexError, ValueError):
        await call.answer("Некорректный запрос.", show_alert=True)
        return

    success, msg = await claim_reward(session, user_id, level)
    if success:
        await session.commit()
        # Refresh and show updated menu
        link = await get_referral_link(user_id)
        stats = await get_referral_stats(session, user_id)
        has_claimable = any(r["is_available"] for r in stats["rewards"])
        has_repeatable = stats["repeatable_available"] > 0
        text = _fmt_referral_menu(stats, link)
        await call.message.edit_text(
            text + f"\n\n{msg}",
            reply_markup=referral_menu_kb(has_claimable, has_repeatable),
            parse_mode="HTML",
        )
    else:
        await call.answer(msg, show_alert=True)

    await call.answer()


# ---------------------------------------------------------------------------
# Callback: claim repeatable reward
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "referral_claim_repeatable")
async def cb_referral_claim_repeatable(call: CallbackQuery, session: AsyncSession) -> None:
    user_id = call.from_user.id

    success, msg = await claim_repeatable_reward(session, user_id)
    if success:
        await session.commit()
        # Refresh and show updated menu
        link = await get_referral_link(user_id)
        stats = await get_referral_stats(session, user_id)
        has_claimable = any(r["is_available"] for r in stats["rewards"])
        has_repeatable = stats["repeatable_available"] > 0
        text = _fmt_referral_menu(stats, link)
        await call.message.edit_text(
            text + f"\n\n{msg}",
            reply_markup=referral_menu_kb(has_claimable, has_repeatable),
            parse_mode="HTML",
        )
    else:
        await call.answer(msg, show_alert=True)

    await call.answer()


# ---------------------------------------------------------------------------
# Callback: referral list
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "referral_list")
async def cb_referral_list(call: CallbackQuery, session: AsyncSession) -> None:
    user_id = call.from_user.id
    stats = await get_referral_stats(session, user_id)

    total = stats["total_referrals"]
    qualified = stats["qualified_count"]
    active = stats["active_count"]

    if total == 0:
        text = (
            "📋 <b>Мои рефералы</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🕳 У тебя ещё нет приглашённых игроков.\n\n"
            "<i>Поделись своей реферальной ссылкой и получай награды!</i>"
        )
    else:
        text = (
            "📋 <b>Мои рефералы</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 Всего приглашено: <code>{total}</code>\n"
            f"🏆 Квалифицированных (≥5 прокачек): <code>{qualified}</code>\n"
            f"✅ Активных (последние 7 дней): <code>{active}</code>\n\n"
            "<i>Реферал считается активным, если заходил в игру "
            "в течение последних 7 дней и имеет ≥5 прокачек.</i>"
        )

    await call.message.edit_text(
        text,
        reply_markup=referral_back_kb(),
        parse_mode="HTML",
    )
    await call.answer()
