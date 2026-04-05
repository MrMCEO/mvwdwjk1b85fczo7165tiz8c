"""
Rating handlers — leaderboards for infections, virus level, immunity level, bio_coins.
"""

from __future__ import annotations

from datetime import UTC, datetime

from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.rating import rating_menu_kb, rating_type_kb
from bot.services.premium import format_username
from bot.services.rating import (
    get_top_immunity_level,
    get_top_infections,
    get_top_richest,
    get_top_virus_level,
)
from bot.utils.emoji import render_virus_name

router = Router(name="rating")

# Medals for places 1-3; numeric for the rest
_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def _place(n: int) -> str:
    return _MEDALS.get(n, f"{n}.")


def _is_status_active(row: dict) -> bool:
    """Return True if the user has any active paid/special status."""
    status = row.get("status", "FREE")
    # OWNER and LEGEND are permanent
    if status in ("OWNER", "BIO_LEGEND"):
        return True
    # All other paid statuses check premium_until
    if status != "FREE":
        pu = row.get("premium_until")
        if pu is not None:
            now = datetime.now(UTC).replace(tzinfo=None)
            return pu > now
    return False


def _get_status_emoji(row: dict) -> str:
    """Return emoji for the user's status."""
    from bot.services.premium import STATUS_CONFIG, UserStatus
    try:
        status = UserStatus(row.get("status", "FREE"))
        return STATUS_CONFIG.get(status, {}).get("emoji", "")
    except ValueError:
        return ""


def _fmt_row_username(row: dict) -> str:
    """Build a display name for a rating row using display_name/prefix if available."""
    base = f"@{row['username']}" if row["username"] else f"id{row['user_id']}"
    active = _is_status_active(row)
    emoji = _get_status_emoji(row)
    return format_username(
        base,
        row.get("premium_prefix"),
        active,
        display_name=row.get("display_name"),
        status_emoji=emoji,
    )


# ---------------------------------------------------------------------------
# Rating menu
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "rating_menu")
async def cb_rating_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "🏆 <b>Рейтинги</b>\n\n<i>Выбери тип рейтинга:</i>",
        reply_markup=rating_menu_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Individual leaderboards
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "rating_infections")
async def cb_rating_infections(callback: CallbackQuery, session: AsyncSession) -> None:
    rows = await get_top_infections(session, limit=10)

    if not rows:
        text = "🦠 <b>Топ по заражениям</b>\n\n<i>Пока никто никого не заразил.</i>"
    else:
        lines = ["🦠 <b>Топ по активным заражениям</b>\n"]
        for i, row in enumerate(rows, start=1):
            display = _fmt_row_username(row)
            lines.append(f"{_place(i)} {display} — <code>{row['count']}</code> заражений")
        lines.append("")
        lines.append(f"<i>Показаны топ-{len(rows)} игроков</i>")
        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=rating_type_kb("infections"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "rating_virus")
async def cb_rating_virus(callback: CallbackQuery, session: AsyncSession) -> None:
    rows = await get_top_virus_level(session, limit=10)

    if not rows:
        text = "⚔️ <b>Топ по уровню вируса</b>\n\n<i>Нет данных.</i>"
    else:
        lines = ["⚔️ <b>Топ по уровню вируса</b>\n"]
        for i, row in enumerate(rows, start=1):
            display = _fmt_row_username(row)
            virus_name = render_virus_name(
                row["virus_name"] or "Безымянный вирус",
                row.get("virus_name_entities"),
            )
            lines.append(
                f"{_place(i)} {display} — ур. <code>{row['level']}</code>"
                f" (<i>{virus_name}</i>)"
            )
        lines.append("")
        lines.append(f"<i>Показаны топ-{len(rows)} игроков</i>")
        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=rating_type_kb("virus"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "rating_immunity")
async def cb_rating_immunity(callback: CallbackQuery, session: AsyncSession) -> None:
    rows = await get_top_immunity_level(session, limit=10)

    if not rows:
        text = "🛡 <b>Топ по уровню иммунитета</b>\n\n<i>Нет данных.</i>"
    else:
        lines = ["🛡 <b>Топ по уровню иммунитета</b>\n"]
        for i, row in enumerate(rows, start=1):
            display = _fmt_row_username(row)
            lines.append(f"{_place(i)} {display} — ур. <code>{row['level']}</code>")
        lines.append("")
        lines.append(f"<i>Показаны топ-{len(rows)} игроков</i>")
        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=rating_type_kb("immunity"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "rating_richest")
async def cb_rating_richest(callback: CallbackQuery, session: AsyncSession) -> None:
    rows = await get_top_richest(session, limit=10)

    if not rows:
        text = "💰 <b>Топ по богатству</b>\n\n<i>Нет данных.</i>"
    else:
        lines = ["💰 <b>Топ богатейших игроков</b>\n"]
        for i, row in enumerate(rows, start=1):
            display = _fmt_row_username(row)
            lines.append(f"{_place(i)} {display} — <code>{row['bio_coins']:,}</code> 🧫")
        lines.append("")
        lines.append(f"<i>Показаны топ-{len(rows)} игроков</i>")
        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=rating_type_kb("richest"),
        parse_mode="HTML",
    )
    await callback.answer()
