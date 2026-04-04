"""
Transfer handlers — peer-to-peer 🧫 BioCoins transfers.

FSM flow:
  TransferStates:
    waiting_for_username → waiting_for_amount → confirm
"""

from __future__ import annotations

from html import escape

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.transfer import transfer_back_kb, transfer_confirm_kb, transfer_menu_kb
from bot.models.user import User
from bot.services.resource import get_balance
from bot.services.transfer import (
    TRANSFER_COMMISSION,
    get_daily_transferred,
    get_transfer_limit,
    transfer_coins,
)

router = Router(name="transfer")


# ---------------------------------------------------------------------------
# FSM State group
# ---------------------------------------------------------------------------


class TransferStates(StatesGroup):
    waiting_for_username = State()
    waiting_for_amount = State()
    confirm = State()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_transfer_menu(daily_used: int, daily_limit: int, bio_balance: int) -> str:
    commission_pct = int(TRANSFER_COMMISSION * 100)
    return (
        "💸 <b>Передача 🧫 BioCoins</b>\n\n"
        f"Твой баланс: <b>{bio_balance} 🧫</b>\n"
        f"Дневной лимит: <b>{daily_used}/{daily_limit} 🧫</b> (использовано/лимит)\n"
        f"Комиссия: <b>{commission_pct}%</b>\n\n"
        "Нажми «💸 Перевести монеты» чтобы начать перевод."
    )


# ---------------------------------------------------------------------------
# Transfer menu
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "transfer_menu")
async def cb_transfer_menu(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Show transfer info page."""
    await state.clear()

    uid = callback.from_user.id
    daily_limit = await get_transfer_limit(session, uid)
    daily_used = await get_daily_transferred(session, uid)
    balance = await get_balance(session, uid)
    bio_balance = balance.get("bio_coins", 0) if balance else 0

    text = _fmt_transfer_menu(daily_used, daily_limit, bio_balance)
    await callback.message.edit_text(
        text,
        reply_markup=transfer_menu_kb(daily_used, daily_limit),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# FSM: start — ask for @username
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "transfer_start")
async def cb_transfer_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Begin transfer FSM: ask for recipient username."""
    await state.set_state(TransferStates.waiting_for_username)
    await callback.message.edit_text(
        "💸 <b>Передача 🧫 BioCoins</b>\n\n"
        "Введите @username получателя\n"
        "(можно без символа @):\n\n"
        "Или нажмите «Назад» для отмены.",
        reply_markup=transfer_back_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(TransferStates.waiting_for_username)
async def msg_transfer_username(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Receive recipient username, validate, then ask for amount."""
    raw = (message.text or "").strip().lstrip("@")

    if not raw:
        await message.answer(
            "❌ Пустой username. Попробуй ещё раз:",
            reply_markup=transfer_back_kb(),
        )
        return

    # Check the user exists (early validation)
    result = await session.execute(
        select(User).where(func.lower(User.username) == raw.lower())
    )
    target = result.scalar_one_or_none()

    if target is None:
        await message.answer(
            f"❌ Игрок <b>@{escape(raw)}</b> не найден в игре.\n"
            "Проверь username и попробуй снова:",
            reply_markup=transfer_back_kb(),
            parse_mode="HTML",
        )
        return

    if target.tg_id == message.from_user.id:
        await message.answer(
            "❌ Нельзя переводить монеты самому себе.",
            reply_markup=transfer_back_kb(),
        )
        return

    await state.update_data(recipient_username=raw, recipient_id=target.tg_id)
    await state.set_state(TransferStates.waiting_for_amount)

    uid = message.from_user.id
    daily_limit = await get_transfer_limit(session, uid)
    daily_used = await get_daily_transferred(session, uid)
    remaining = max(0, daily_limit - daily_used)
    balance = await get_balance(session, uid)
    bio_balance = balance.get("bio_coins", 0) if balance else 0
    commission_pct = int(TRANSFER_COMMISSION * 100)

    await message.answer(
        f"✅ Получатель: <b>@{escape(raw)}</b>\n\n"
        f"Твой баланс: <b>{bio_balance} 🧫</b>\n"
        f"Доступный лимит: <b>{remaining} 🧫</b> из <b>{daily_limit}</b>\n"
        f"Комиссия: <b>{commission_pct}%</b> (получатель получит 90% суммы)\n\n"
        "Введи сумму перевода (целое число 🧫):\n\n"
        "Или нажми «Назад» для отмены.",
        reply_markup=transfer_back_kb(),
        parse_mode="HTML",
    )


@router.message(TransferStates.waiting_for_amount)
async def msg_transfer_amount(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Receive amount, validate, show confirmation screen."""
    raw = (message.text or "").strip()

    try:
        amount = int(raw)
    except ValueError:
        await message.answer(
            "❌ Введи целое число. Попробуй ещё раз:",
            reply_markup=transfer_back_kb(),
        )
        return

    if amount <= 0:
        await message.answer(
            "❌ Сумма должна быть больше нуля. Попробуй ещё раз:",
            reply_markup=transfer_back_kb(),
        )
        return

    # Guard against absurdly large inputs (well above any realistic balance)
    MAX_TRANSFER_INPUT = 10_000_000
    if amount > MAX_TRANSFER_INPUT:
        await message.answer(
            f"❌ Слишком большая сумма. Максимум: {MAX_TRANSFER_INPUT:,} 🧫",
            reply_markup=transfer_back_kb(),
        )
        return

    data = await state.get_data()
    recipient_username = data.get("recipient_username", "")

    uid = message.from_user.id
    daily_limit = await get_transfer_limit(session, uid)
    daily_used = await get_daily_transferred(session, uid)
    remaining = max(0, daily_limit - daily_used)

    if amount > remaining:
        await message.answer(
            f"❌ Превышен дневной лимит.\n"
            f"Доступно: <b>{remaining} 🧫</b> из <b>{daily_limit}</b>\n\n"
            "Введи другую сумму:",
            reply_markup=transfer_back_kb(),
            parse_mode="HTML",
        )
        return

    balance = await get_balance(session, uid)
    bio_balance = balance.get("bio_coins", 0) if balance else 0

    if amount > bio_balance:
        await message.answer(
            f"❌ Недостаточно 🧫 BioCoins.\n"
            f"Нужно: <b>{amount} 🧫</b>, у тебя: <b>{bio_balance} 🧫</b>\n\n"
            "Введи другую сумму:",
            reply_markup=transfer_back_kb(),
            parse_mode="HTML",
        )
        return

    commission = max(1, int(amount * TRANSFER_COMMISSION))
    received = amount - commission

    await state.update_data(amount=amount)
    await state.set_state(TransferStates.confirm)

    await message.answer(
        f"💸 <b>Подтверждение перевода</b>\n\n"
        f"Получатель: <b>@{escape(recipient_username)}</b>\n"
        f"Отправляете: <b>{amount} 🧫</b>\n"
        f"Комиссия (10%): <b>{commission} 🧫</b>\n"
        f"Получит: <b>{received} 🧫</b>\n\n"
        "Подтвердить перевод?",
        reply_markup=transfer_confirm_kb(recipient_username, amount, received, commission),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# FSM: confirm
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "transfer_confirm")
async def cb_transfer_confirm(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Execute the confirmed transfer."""
    data = await state.get_data()
    recipient_username = data.get("recipient_username", "")
    amount = data.get("amount", 0)
    await state.clear()

    if not recipient_username or not amount:
        await callback.answer("❌ Сессия устарела. Начни заново.", show_alert=True)
        return

    success, msg = await transfer_coins(
        session, callback.from_user.id, recipient_username, amount
    )

    uid = callback.from_user.id
    daily_limit = await get_transfer_limit(session, uid)
    daily_used = await get_daily_transferred(session, uid)
    balance = await get_balance(session, uid)
    bio_balance = balance.get("bio_coins", 0) if balance else 0

    full_text = msg + "\n\n" + _fmt_transfer_menu(daily_used, daily_limit, bio_balance)
    await callback.message.edit_text(
        full_text,
        reply_markup=transfer_menu_kb(daily_used, daily_limit),
        parse_mode="HTML",
    )
    await callback.answer()
