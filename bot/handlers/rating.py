"""
Rating handlers — leaderboards for infections, virus level, immunity level, bio_coins.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.rating import rating_menu_kb, rating_type_kb
from bot.services.rating import (
    get_top_immunity_level,
    get_top_infections,
    get_top_richest,
    get_top_virus_level,
)

router = Router(name="rating")

# Medals for places 1-3; numeric for the rest
_MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


def _place(n: int) -> str:
    return _MEDALS.get(n, f"{n}.")


# ---------------------------------------------------------------------------
# Rating menu
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "rating_menu")
async def cb_rating_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "🏆 <b>Рейтинги</b>\n\nВыбери тип рейтинга:",
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
        text = "🦠 <b>Топ по заражениям</b>\n\nПока никто никого не заразил."
    else:
        lines = ["🦠 <b>Топ по активным заражениям</b>\n"]
        for i, row in enumerate(rows, start=1):
            username = f"@{row['username']}" if row["username"] else f"id{row['user_id']}"
            lines.append(f"{_place(i)} {username} — <b>{row['count']}</b> заражений")
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
        text = "⚔️ <b>Топ по уровню вируса</b>\n\nНет данных."
    else:
        lines = ["⚔️ <b>Топ по уровню вируса</b>\n"]
        for i, row in enumerate(rows, start=1):
            username = f"@{row['username']}" if row["username"] else f"id{row['user_id']}"
            virus_name = row["virus_name"] or "Безымянный вирус"
            lines.append(
                f"{_place(i)} {username} — <b>ур. {row['level']}</b>"
                f" (<i>{virus_name}</i>)"
            )
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
        text = "🛡 <b>Топ по уровню иммунитета</b>\n\nНет данных."
    else:
        lines = ["🛡 <b>Топ по уровню иммунитета</b>\n"]
        for i, row in enumerate(rows, start=1):
            username = f"@{row['username']}" if row["username"] else f"id{row['user_id']}"
            lines.append(f"{_place(i)} {username} — <b>ур. {row['level']}</b>")
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
        text = "💰 <b>Топ по богатству</b>\n\nНет данных."
    else:
        lines = ["💰 <b>Топ богатейших игроков</b>\n"]
        for i, row in enumerate(rows, start=1):
            username = f"@{row['username']}" if row["username"] else f"id{row['user_id']}"
            lines.append(f"{_place(i)} {username} — <b>{row['bio_coins']:,}</b> 🧫")
        text = "\n".join(lines)

    await callback.message.edit_text(
        text,
        reply_markup=rating_type_kb("richest"),
        parse_mode="HTML",
    )
    await callback.answer()
