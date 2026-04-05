"""Virus section handlers — view stats, upgrade branches, and rename virus."""

from __future__ import annotations

import json

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.virus import virus_menu_kb
from bot.models.virus import Virus
from bot.services.premium import get_virus_name_limit
from bot.services.upgrade import get_virus_stats, upgrade_virus_branch
from bot.utils.chat import smart_reply
from bot.utils.emoji import render_virus_name
from bot.utils.throttle import check_throttle

router = Router(name="virus")


class VirusStates(StatesGroup):
    waiting_for_name = State()


def _rename_cancel_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="virus_menu")
    return builder.as_markup()

# Maps short callback suffix → full branch key
_SHORT_TO_BRANCH = {
    "LET": "LETHALITY",
    "CON": "CONTAGION",
    "STE": "STEALTH",
}


def _fmt_virus_stats(data: dict) -> str:
    if "error" in data:
        return f"❌ {data['error']}"

    v = data["virus"]
    upgrades = data["upgrades"]

    display_name = render_virus_name(v["name"], v.get("name_entities_json"))
    total_level = v["level"]

    lines = [
        "🦠 <b>Мой вирус</b>\n",
        f"Имя: <b>{display_name}</b>",
        f"Уровень: <b>{total_level}</b>",
        "",
        "<b>Ветки прокачки:</b>",
    ]

    icons = {"LETHALITY": "☠️", "CONTAGION": "🦠", "STEALTH": "👁"}
    for branch_key, info in upgrades.items():
        icon = icons.get(branch_key, "•")
        next_cost = info.get("next_cost")
        cost_text = "МАКС" if next_cost is None else f"{next_cost} 🧫"
        lines.append(
            f"{icon} {info['name']}: ур. <b>{info['level']}</b>  │  {cost_text}"
        )

    return "\n".join(lines)


@router.callback_query(lambda c: c.data == "virus_menu")
async def cb_virus_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    data = await get_virus_stats(session, callback.from_user.id)
    text = _fmt_virus_stats(data)
    upgrades = data.get("upgrades")
    await callback.message.edit_text(
        text, reply_markup=virus_menu_kb(upgrades), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("upg_v_"))
async def cb_upgrade_virus(callback: CallbackQuery, session: AsyncSession) -> None:
    """Upgrade virus branch immediately on button press."""
    remaining = check_throttle(callback.from_user.id, "upgrade_virus")
    if remaining > 0:
        await callback.answer(f"Повторите попытку через {remaining:.0f} сек.", show_alert=True)
        return

    short = callback.data[6:].upper()
    branch = _SHORT_TO_BRANCH.get(short)
    if not branch:
        await callback.answer("Неизвестная ветка.", show_alert=True)
        return

    success, message = await upgrade_virus_branch(session, callback.from_user.id, branch)

    if not success:
        await callback.answer(message, show_alert=True)
        return

    data = await get_virus_stats(session, callback.from_user.id)
    text = _fmt_virus_stats(data)
    upgrades = data.get("upgrades")
    await callback.message.edit_text(
        f"✅ {message}\n\n" + text,
        reply_markup=virus_menu_kb(upgrades),
        parse_mode="HTML",
    )
    await callback.answer("Прокачано!")


@router.callback_query(lambda c: c.data == "rename_virus")
async def cb_rename_virus(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Begin FSM flow to rename the player's virus."""
    name_limit = await get_virus_name_limit(session, callback.from_user.id)
    await state.set_state(VirusStates.waiting_for_name)
    await callback.message.edit_text(
        f"✏️ <b>Переименование вируса</b>\n\n"
        f"Введи новое название вируса (максимум {name_limit} символов):",
        reply_markup=_rename_cancel_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(VirusStates.waiting_for_name)
async def msg_virus_name(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Handle the new virus name input."""
    raw = (message.text or "").strip()

    name_limit = await get_virus_name_limit(session, message.from_user.id)

    if not raw:
        await smart_reply(
            message,
            "❌ Имя не может быть пустым. Введи название вируса:",
            reply_markup=_rename_cancel_kb(),
        )
        return

    if len(raw) > name_limit:
        await smart_reply(
            message,
            f"❌ Максимум {name_limit} символов. Попробуй снова:",
            reply_markup=_rename_cancel_kb(),
        )
        return

    # Извлечь custom_emoji entities
    entities_data = []
    if message.entities:
        for ent in message.entities:
            if ent.type == "custom_emoji" and ent.custom_emoji_id:
                entities_data.append({
                    "offset": ent.offset,
                    "length": ent.length,
                    "custom_emoji_id": ent.custom_emoji_id,
                })

    # Кастомные эмодзи требуют Telegram Premium
    if entities_data:
        user = message.from_user
        is_premium = bool(getattr(user, "is_premium", False))
        if not is_premium:
            await smart_reply(
                message,
                "⭐ Кастомные эмодзи доступны только с <b>Премиум-подпиской</b> Telegram.\n\n"
                "Введи обычное имя (обычные эмодзи разрешены):",
                reply_markup=_rename_cancel_kb(),
            )
            return

    # Сохраняем RAW имя без html.escape — экранирование выполняется в render_virus_name.
    # Это гарантирует, что entity offsets (из Telegram) совпадают с позициями символов.

    # Persist the new name
    result = await session.execute(
        select(Virus).where(Virus.owner_id == message.from_user.id)
    )
    virus = result.scalar_one_or_none()
    if virus is None:
        await state.clear()
        await smart_reply(message, "❌ Вирус не найден.")
        return

    virus.name = raw
    virus.name_entities_json = json.dumps(entities_data) if entities_data else None
    await session.flush()

    await state.clear()

    # Show confirmation and updated virus menu
    data = await get_virus_stats(session, message.from_user.id)
    menu_text = _fmt_virus_stats(data)
    upgrades = data.get("upgrades")
    display_name = render_virus_name(raw, virus.name_entities_json)
    await smart_reply(
        message,
        f"✅ Вирус назван: <b>{display_name}</b>\n\n" + menu_text,
        reply_markup=virus_menu_kb(upgrades),
    )
