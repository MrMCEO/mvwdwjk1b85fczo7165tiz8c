"""Attack section handlers — target lookup, attack, infections list, cure."""

from __future__ import annotations

from html import escape

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.attack import attack_confirm_kb, attack_menu_kb, infections_list_kb
from bot.keyboards.common import back_button
from bot.models.user import User
from bot.services.combat import (
    attack_player,
    get_active_infections_by,
    get_active_infections_on,
    try_cure,
)
from bot.services.notifications import should_notify

router = Router(name="attack")


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
        "Заражай других игроков своим вирусом!\n"
        "Каждая атака имеет кулдаун 30 минут.",
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
        "Напиши username игрока которого хочешь атаковать\n"
        "(можно без символа @).\n\n"
        "Или нажми «Назад» для отмены:",
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
        await message.answer(
            "❌ Пустой username. Попробуй ещё раз:",
            reply_markup=back_button("attack_menu"),
        )
        return

    # Lookup target — case-insensitive to handle e.g. "johndoe" vs "JohnDoe"
    result = await session.execute(
        select(User).where(func.lower(User.username) == raw.lower())
    )
    target: User | None = result.scalar_one_or_none()

    if target is None:
        await message.answer(
            f"❌ Игрок <b>@{escape(raw)}</b> не найден.\n"
            "Убедись что он зарегистрирован в игре.",
            reply_markup=back_button("attack_menu"),
            parse_mode="HTML",
        )
        return

    if target.tg_id == message.from_user.id:
        await message.answer(
            "❌ Нельзя атаковать самого себя.",
            reply_markup=back_button("attack_menu"),
        )
        return

    await state.clear()

    target_display = f"@{target.username}" if target.username else f"id{target.tg_id}"
    await message.answer(
        f"⚔️ <b>Подтверждение атаки</b>\n\n"
        f"Цель: <b>{target_display}</b>\n\n"
        "Атаковать этого игрока?",
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

    success, msg, victim_notification = await attack_player(
        session, callback.from_user.id, victim_id
    )

    icon = "✅" if success else "❌"
    await callback.message.edit_text(
        f"{icon} {msg}",
        reply_markup=attack_menu_kb(),
        parse_mode="HTML",
    )
    await callback.answer("Атака выполнена!" if success else "Атака провалена!")

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
            except Exception:
                pass


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
        f"Исходящих (жертвы): <b>{out_count}</b>\n"
        f"Входящих (на мне): <b>{in_count}</b>\n\n"
        "Выбери категорию:"
    )
    builder = InlineKeyboardBuilder()
    if out_count:
        builder.button(text=f"⚔️ Мои жертвы ({out_count})", callback_data="inf_pg_by_0")
    if in_count:
        builder.button(text=f"🤒 Кто заражает меня ({in_count})", callback_data="inf_pg_on_0")
    builder.button(text="◀️ Назад", callback_data="attack_menu")
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

    text = f"{title}  (стр. {page + 1}/{total_pages})\n\n"

    if mode == "on":
        cure_hint = "Нажми на строку заражения чтобы вылечиться."
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

    success, msg = await try_cure(session, callback.from_user.id, infection_id)

    if success:
        # Refresh the incoming infections list
        infections = await get_active_infections_on(session, callback.from_user.id)
        list_text = (
            "🤒 <b>Кто заражает меня</b>\n\n"
            f"✅ {msg}"
        )
        await callback.message.edit_text(
            list_text,
            reply_markup=infections_list_kb(infections, page=0, mode="on"),
            parse_mode="HTML",
        )
    else:
        await callback.answer(f"❌ {msg}", show_alert=True)


@router.callback_query(lambda c: c.data and c.data.startswith("inf_info_"))
async def cb_inf_info(callback: CallbackQuery) -> None:
    """Noop handler for outgoing infection info buttons."""
    await callback.answer("Информация об исходящем заражении.", show_alert=False)


@router.callback_query(lambda c: c.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    """Pagination counter button — does nothing."""
    await callback.answer()
