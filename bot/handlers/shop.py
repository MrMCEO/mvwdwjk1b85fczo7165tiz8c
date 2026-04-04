"""Shop section handlers — PremiumCoins packages (stubs) and conversion."""

from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.common import back_button
from bot.keyboards.shop import PACKAGES, shop_menu_kb
from bot.services.donation import EXCHANGE_RATE, convert_premium_to_bio
from bot.services.resource import get_balance

router = Router(name="shop")


class ShopConvertStates(StatesGroup):
    waiting_for_amount = State()


def _build_shop_text(bio: int, premium: int) -> str:
    lines = [
        "💎 <b>Магазин PremiumCoins</b>\n",
        "Курс: 1 💎 = 1₽\n",
        "Пакеты:",
    ]
    for pkg in PACKAGES:
        bonus_str = f" (бонус +{int(pkg['bonus'] * 100)}%)" if pkg["bonus"] else ""
        lines.append(f"📦 {pkg['amount']} 💎 — {pkg['price_rub']}₽{bonus_str}")
    lines += [
        f"\n💱 Конвертация: 1 💎 = {EXCHANGE_RATE} 🧫",
        "\n"
        f"Твой баланс: <b>{premium:,} 💎</b> | <b>{bio:,} 🧫</b>\n",
        "Для покупки 💎 свяжитесь с администратором\n"
        "или используйте промокод: /promo КОД",
    ]
    return "\n".join(lines)


@router.callback_query(lambda c: c.data == "shop_menu")
async def cb_shop_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    balance = await get_balance(session, callback.from_user.id)
    bio = balance.get("bio_coins", 0) if balance else 0
    premium = balance.get("premium_coins", 0) if balance else 0

    await callback.message.edit_text(
        _build_shop_text(bio, premium),
        reply_markup=shop_menu_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("buy_pkg_"))
async def cb_buy_package_stub(callback: CallbackQuery) -> None:
    """Stub handler for PremiumCoins package purchase buttons."""
    pkg_id = callback.data[len("buy_pkg_"):]
    pkg = next((p for p in PACKAGES if p["id"] == pkg_id), None)

    if pkg is None:
        await callback.answer("Пакет не найден.", show_alert=True)
        return

    bonus_line = f" (+{int(pkg['bonus'] * 100)}% бонус)" if pkg["bonus"] else ""
    text = (
        f"📦 <b>Пакет: {pkg['amount']} 💎 за {pkg['price_rub']}₽{bonus_line}</b>\n\n"
        "Покупка пока недоступна напрямую.\n"
        "Для пополнения обратитесь к администратору\n"
        "или используйте промокод: /promo КОД"
    )
    await callback.message.edit_text(
        text,
        reply_markup=back_button("shop_menu"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "shop_convert_start")
async def cb_convert_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start premium → bio conversion flow (from shop menu)."""
    await state.set_state(ShopConvertStates.waiting_for_amount)
    await callback.message.edit_text(
        f"💱 <b>Конвертация 💎 PremiumCoins → 🧫 BioCoins</b>\n\n"
        f"Курс: 1 💎 = {EXCHANGE_RATE} 🧫\n\n"
        "Введи количество 💎 PremiumCoins для конвертации\n"
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


# ---------------------------------------------------------------------------
# Legacy callback aliases kept for backwards compatibility
# ---------------------------------------------------------------------------

@router.callback_query(lambda c: c.data == "shop_convert_premium")
async def cb_convert_start_legacy(callback: CallbackQuery, state: FSMContext) -> None:
    """Redirect old callback name to the new handler."""
    await cb_convert_start(callback, state)


@router.callback_query(lambda c: c.data and c.data.startswith("buy_p_"))
async def cb_buy_premium_stub_legacy(callback: CallbackQuery) -> None:
    """Redirect old stub callbacks to a generic notice."""
    await callback.answer(
        "💳 Покупка 💎 PremiumCoins временно недоступна.\n"
        "Используйте кнопки из меню магазина.",
        show_alert=True,
    )
