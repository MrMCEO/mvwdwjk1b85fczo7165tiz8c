"""Attack section handlers — target lookup, attack, infections list, cure."""

from __future__ import annotations

import logging
from html import escape

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.keyboards.attack import attack_confirm_kb, attack_menu_kb, infections_list_kb
from bot.keyboards.common import back_button
from bot.models.user import User
from bot.services.combat import (
    attack_player,
    get_active_infections_by,
    get_active_infections_on,
    get_random_target,
    try_cure,
)
from bot.services.notifications import should_notify
from bot.utils.chat import dlvl, smart_reply
from bot.utils.throttle import check_throttle

router = Router(name="attack")
logger = logging.getLogger(__name__)


class AttackStates(StatesGroup):
    waiting_for_username = State()


# ---------------------------------------------------------------------------
# Attack menu
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "attack_menu")
async def cb_attack_menu(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        "⚔️ <b>Атака</b>\n\n"
        "<i>Выбери цель для заражения.\n"
        "Введи @username или используй быструю атаку.</i>",
        reply_markup=attack_menu_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Enter target username via FSM
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "attack_enter")
async def cb_attack_enter(callback: CallbackQuery, state: FSMContext) -> None:
    """Prompt the user to type a target @username."""
    await state.set_state(AttackStates.waiting_for_username)
    await callback.message.edit_text(
        "⚔️ <b>Введи @username цели</b>\n\n"
        "<i>Напиши username игрока которого хочешь атаковать\n"
        "(можно без символа @).</i>",
        reply_markup=back_button("attack_menu"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(AttackStates.waiting_for_username)
async def msg_attack_username(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Look up the target by username and show a confirmation keyboard."""
    raw = (message.text or "").strip().lstrip("@")

    if not raw:
        await smart_reply(
            message,
            "❌ Пустой username. Попробуй ещё раз:",
            reply_markup=back_button("attack_menu"),
        )
        return

    # Lookup target — case-insensitive to handle e.g. "johndoe" vs "JohnDoe"
    result = await session.execute(
        select(User)
        .where(func.lower(User.username) == raw.lower())
        .options(selectinload(User.virus), selectinload(User.immunity))
    )
    target: User | None = result.scalar_one_or_none()

    if target is None:
        await smart_reply(
            message,
            f"❌ Игрок <b>@{escape(raw)}</b> не найден.\n"
            "Убедись что он зарегистрирован в игре.",
            reply_markup=back_button("attack_menu"),
        )
        return

    if target.tg_id == message.from_user.id:
        await smart_reply(
            message,
            "❌ Нельзя атаковать самого себя.",
            reply_markup=back_button("attack_menu"),
        )
        return

    await state.clear()

    target_display = f"@{target.username}" if target.username else f"id{target.tg_id}"
    virus_level = target.virus.level if target.virus else 0
    immunity_level = target.immunity.level if target.immunity else 0
    await smart_reply(
        message,
        f"⚔️ <b>Подтверждение атаки</b>\n\n"
        f"🎯 Цель: <b>{target_display}</b>\n"
        f"🦠 Вирус цели: ур. <code>{dlvl(virus_level)}</code>\n"
        f"🛡 Иммунитет цели: ур. <code>{dlvl(immunity_level)}</code>\n\n"
        "<i>Атаковать?</i>",
        reply_markup=attack_confirm_kb(target.tg_id),
    )


# ---------------------------------------------------------------------------
# Random attack
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "random_attack")
async def cb_random_attack(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Pick a random eligible target and show the confirmation screen."""
    remaining = check_throttle(callback.from_user.id, "random_attack", cooldown=10.0)
    if remaining > 0:
        await callback.answer(
            f"⏳ Подождите {int(remaining)} сек. перед следующей случайной атакой.",
            show_alert=True,
        )
        return

    # Acknowledge immediately to prevent query timeout
    await callback.answer()

    target = await get_random_target(session, callback.from_user.id)

    if target is None:
        await callback.message.edit_text(
            "🎲 <b>Случайная атака</b>\n\n"
            "❌ Нет доступных целей для атаки.\n"
            "<i>(Все игроки уже заражены или ты единственный участник.)</i>",
            reply_markup=attack_menu_kb(),
            parse_mode="HTML",
        )
        return

    virus_level = target.virus.level if target.virus else 0
    immunity_level = target.immunity.level if target.immunity else 0
    target_display = f"@{escape(target.username)}" if target.username else f"id{target.tg_id}"

    await callback.message.edit_text(
        f"⚔️ <b>Подтверждение атаки</b>\n\n"
        f"🎯 Цель: <b>{target_display}</b>\n"
        f"🦠 Вирус цели: ур. <code>{dlvl(virus_level)}</code>\n"
        f"🛡 Иммунитет цели: ур. <code>{dlvl(immunity_level)}</code>\n\n"
        "<i>Атаковать?</i>",
        reply_markup=attack_confirm_kb(target.tg_id),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Confirm attack
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data and c.data.startswith("atk_"))
async def cb_confirm_attack(callback: CallbackQuery, session: AsyncSession) -> None:
    """Execute the attack after user confirms."""
    try:
        victim_id = int(callback.data[4:])
    except ValueError:
        await callback.answer("Неверные данные атаки.", show_alert=True)
        return

    # Acknowledge immediately to prevent query timeout
    await callback.answer()

    success, msg, victim_notification = await attack_player(
        session, callback.from_user.id, victim_id
    )

    icon = "✅" if success else "❌"
    await callback.message.edit_text(
        f"{icon} {msg}",
        reply_markup=attack_menu_kb(),
        parse_mode="HTML",
    )

    # Notify the victim about being infected (best-effort — ignore if blocked)
    if victim_notification:
        notify_type = victim_notification.get("notify_type", "attacks")
        if await should_notify(session, victim_notification["user_id"], notify_type):
            try:
                await callback.bot.send_message(
                    chat_id=victim_notification["user_id"],
                    text=victim_notification["message"],
                    parse_mode="HTML",
                )
            except Exception as exc:
                logger.debug("Failed to notify victim %d: %s", victim_notification["user_id"], exc)


# ---------------------------------------------------------------------------
# My infections list (outgoing) with pagination
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "my_infections")
async def cb_my_infections(callback: CallbackQuery, session: AsyncSession) -> None:
    infections = await get_active_infections_by(session, callback.from_user.id)
    incoming = await get_active_infections_on(session, callback.from_user.id)

    out_count = len(infections)
    in_count = len(incoming)

    if not infections and not incoming:
        text = (
            "🦠 <b>Мои заражения</b>\n\n"
            "Нет активных заражений."
        )
        await callback.message.edit_text(
            text, reply_markup=attack_menu_kb(), parse_mode="HTML"
        )
        await callback.answer()
        return

    text = (
        f"🦠 <b>Мои заражения</b>\n\n"
        f"⚔️ Исходящих (жертвы): <code>{out_count}</code>\n"
        f"🤒 Входящих (на мне): <code>{in_count}</code>\n\n"
        "<i>Выбери категорию:</i>"
    )
    builder = InlineKeyboardBuilder()
    if out_count:
        builder.button(text=f"⚔️ Мои жертвы ({out_count})", callback_data="inf_pg_by_0")
    if in_count:
        builder.button(text=f"🤒 Кто заражает меня ({in_count})", callback_data="inf_pg_on_0")
    builder.button(text="🔙 Назад", callback_data="attack_menu")
    builder.adjust(1)

    await callback.message.edit_text(
        text, reply_markup=builder.as_markup(), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("inf_pg_"))
async def cb_infections_page(callback: CallbackQuery, session: AsyncSession) -> None:
    """
    Handle paginated infection list.
    Callback format: inf_pg_{mode}_{page}  e.g. inf_pg_by_0  or  inf_pg_on_2
    """
    parts = callback.data.split("_")  # ['inf', 'pg', mode, page]
    if len(parts) != 4:
        await callback.answer("Неверный формат.", show_alert=True)
        return

    mode = parts[2]   # "by" or "on"
    if mode not in ("by", "on"):
        await callback.answer("Неверный формат.", show_alert=True)
        return

    try:
        page = int(parts[3])
    except ValueError:
        page = 0
    page = max(0, page)  # prevent negative pages

    if mode == "by":
        infections = await get_active_infections_by(session, callback.from_user.id)
        title = "⚔️ <b>Мои жертвы</b>"
    else:
        infections = await get_active_infections_on(session, callback.from_user.id)
        title = "🤒 <b>Кто заражает меня</b>"

    if not infections:
        await callback.message.edit_text(
            f"{title}\n\nСписок пуст.",
            reply_markup=attack_menu_kb(),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    page_size = 5
    total_pages = max(1, (len(infections) + page_size - 1) // page_size)

    text = f"{title}  (стр. <code>{page + 1}/{total_pages}</code>)\n\n"

    if mode == "on":
        cure_hint = "<i>Нажми на кнопку заражения чтобы вылечиться.</i>"
        text += cure_hint + "\n"

    await callback.message.edit_text(
        text,
        reply_markup=infections_list_kb(infections, page=page, mode=mode),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Cure infection
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data and c.data.startswith("cure_"))
async def cb_cure(callback: CallbackQuery, session: AsyncSession) -> None:
    try:
        infection_id = int(callback.data[5:])
    except ValueError:
        await callback.answer("Неверный ID заражения.", show_alert=True)
        return

    # Acknowledge immediately to prevent query timeout
    await callback.answer()

    success, msg = await try_cure(session, callback.from_user.id, infection_id)

    infections = await get_active_infections_on(session, callback.from_user.id)
    icon = "✅" if success else "❌"
    list_text = (
        "🤒 <b>Кто заражает меня</b>\n\n"
        f"{icon} {msg}"
    )
    await callback.message.edit_text(
        list_text,
        reply_markup=infections_list_kb(infections, page=0, mode="on"),
        parse_mode="HTML",
    )


@router.callback_query(lambda c: c.data and c.data.startswith("inf_info_"))
async def cb_inf_info(callback: CallbackQuery) -> None:
    """Noop handler for outgoing infection info buttons."""
    await callback.answer("Информация об исходящем заражении.", show_alert=False)


@router.callback_query(lambda c: c.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    """Pagination counter button — does nothing."""
    await callback.answer()
