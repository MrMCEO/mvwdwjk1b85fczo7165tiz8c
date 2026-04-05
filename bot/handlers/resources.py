"""Resources section handlers — mine, daily bonus, convert premium."""

from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.common import back_button
from bot.keyboards.resources import resources_menu_kb
from bot.services.donation import EXCHANGE_RATE, convert_premium_to_bio
from bot.services.resource import claim_daily_bonus, get_balance, mine_resources
from bot.utils.chat import smart_reply

router = Router(name="resources")


class ConvertStates(StatesGroup):
    waiting_for_amount = State()


def _fmt_resources(balance: dict) -> str:
    bio = balance.get("bio_coins", 0)
    premium = balance.get("premium_coins", 0)
    return (
        "💰 <b>Ресурсы</b>\n\n"
        f"🧫 BioCoins: <b>{bio:,}</b>\n"
        f"💎 PremiumCoins: <b>{premium:,}</b>"
    )


@router.callback_query(lambda c: c.data == "resources_menu")
async def cb_resources_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    balance = await get_balance(session, callback.from_user.id)
    text = _fmt_resources(balance) if balance else "❌ Игрок не найден."
    await callback.message.edit_text(
        text, reply_markup=resources_menu_kb(), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "mine")
async def cb_mine(callback: CallbackQuery, session: AsyncSession) -> None:
    amount, message = await mine_resources(session, callback.from_user.id)

    balance = await get_balance(session, callback.from_user.id)
    header = _fmt_resources(balance) if balance else ""

    icon = "✅" if amount > 0 else "⏳"
    text = f"{header}\n\n{icon} {message}"

    await callback.message.edit_text(
        text, reply_markup=resources_menu_kb(), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "daily_bonus")
async def cb_daily_bonus(callback: CallbackQuery, session: AsyncSession) -> None:
    amount, message = await claim_daily_bonus(session, callback.from_user.id)

    balance = await get_balance(session, callback.from_user.id)
    header = _fmt_resources(balance) if balance else ""

    icon = "🎁" if amount > 0 else "⏳"
    text = f"{header}\n\n{icon} {message}"

    await callback.message.edit_text(
        text, reply_markup=resources_menu_kb(), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "convert_premium")
async def cb_convert_premium_start(
    callback: CallbackQuery, state: FSMContext
) -> None:
    """Ask user how many premium coins to convert."""
    await state.set_state(ConvertStates.waiting_for_amount)
    await callback.message.edit_text(
        f"💱 <b>Конвертация 💎 PremiumCoins → 🧫 BioCoins</b>\n\n"
        f"Курс: 1 💎 PremiumCoin = {EXCHANGE_RATE} 🧫 BioCoins\n\n"
        "Введи количество 💎 PremiumCoins для конвертации\n"
        "или нажми «Назад» для отмены:",
        reply_markup=back_button("resources_menu"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ConvertStates.waiting_for_amount)
async def msg_convert_amount(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Process the amount the user typed."""
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        await smart_reply(
            message,
            "❌ Введи целое положительное число.",
            reply_markup=back_button("resources_menu"),
        )
        return

    amount = int(raw)
    if amount > 1_000_000_000:
        await smart_reply(
            message,
            "❌ Слишком большое число.",
            reply_markup=back_button("resources_menu"),
        )
        return

    await state.clear()

    success, msg = await convert_premium_to_bio(session, message.from_user.id, amount)
    icon = "✅" if success else "❌"
    await smart_reply(
        message,
        f"{icon} {msg}",
        reply_markup=resources_menu_kb(),
    )
