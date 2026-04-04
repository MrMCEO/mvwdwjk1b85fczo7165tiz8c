"""Shop section handlers — premium purchases (stubs) and conversion."""

from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.common import back_button
from bot.keyboards.shop import shop_menu_kb
from bot.services.donation import EXCHANGE_RATE, convert_premium_to_bio
from bot.services.resource import get_balance

router = Router(name="shop")


class ShopConvertStates(StatesGroup):
    waiting_for_amount = State()


@router.callback_query(lambda c: c.data == "shop_menu")
async def cb_shop_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    balance = await get_balance(session, callback.from_user.id)
    bio = balance.get("bio_coins", 0) if balance else 0
    premium = balance.get("premium_coins", 0) if balance else 0

    text = (
        "💎 <b>Магазин</b>\n\n"
        f"Твой баланс:\n"
        f"🧫 Bio coins: <b>{bio:,}</b>\n"
        f"💎 Premium coins: <b>{premium:,}</b>\n\n"
        f"Курс обмена: 1 premium = {EXCHANGE_RATE} bio_coins\n\n"
        "Покупка premium coins — <i>интеграция платежей в разработке</i> 🚧"
    )
    await callback.message.edit_text(
        text, reply_markup=shop_menu_kb(), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("buy_p_"))
async def cb_buy_premium_stub(callback: CallbackQuery) -> None:
    """Stub handler for premium purchase buttons."""
    await callback.answer(
        "💳 Покупка premium coins временно недоступна.\n"
        "Интеграция платёжной системы в разработке.",
        show_alert=True,
    )


@router.callback_query(lambda c: c.data == "shop_convert_premium")
async def cb_convert_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start premium → bio conversion flow from the shop."""
    await state.set_state(ShopConvertStates.waiting_for_amount)
    await callback.message.edit_text(
        f"💱 <b>Конвертация premium → bio</b>\n\n"
        f"Курс: 1 premium = {EXCHANGE_RATE} bio_coins\n\n"
        "Введи количество premium coins для конвертации\n"
        "или нажми «Назад» для отмены:",
        reply_markup=back_button("shop_menu"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(ShopConvertStates.waiting_for_amount)
async def msg_shop_convert_amount(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    raw = (message.text or "").strip()
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer(
            "❌ Введи целое положительное число.",
            reply_markup=back_button("shop_menu"),
        )
        return

    amount = int(raw)
    if amount > 1_000_000_000:
        await message.answer(
            "❌ Слишком большое число.",
            reply_markup=back_button("shop_menu"),
        )
        return
    await state.clear()

    success, msg = await convert_premium_to_bio(session, message.from_user.id, amount)
    icon = "✅" if success else "❌"
    await message.answer(
        f"{icon} {msg}",
        reply_markup=shop_menu_kb(),
        parse_mode="HTML",
    )
