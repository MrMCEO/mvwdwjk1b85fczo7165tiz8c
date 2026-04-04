"""
Black market handlers — P2P trading and hit contracts.

FSM flows:
  - MarketSellStates:     waiting_for_amount → waiting_for_price → confirm
  - MarketBuyStates:      waiting_for_amount → waiting_for_price → confirm
  - MarketContractStates: waiting_for_username → waiting_for_reward → confirm
"""

from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.common import back_button
from bot.keyboards.market import (
    PAGE_SIZE,
    market_contracts_kb,
    market_listings_kb,
    market_menu_kb,
    market_my_kb,
)
from bot.models.market import ListingStatus, ListingType
from bot.services.market import (
    cancel_listing,
    claim_hit_contract,
    create_buy_listing,
    create_hit_contract,
    create_sell_listing,
    fulfill_listing,
    get_active_listings,
    get_my_listings,
)

router = Router(name="market")


# ---------------------------------------------------------------------------
# FSM State groups
# ---------------------------------------------------------------------------


class MarketSellStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_price = State()


class MarketBuyStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_price = State()


class MarketContractStates(StatesGroup):
    waiting_for_username = State()
    waiting_for_reward = State()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TYPE_LABEL = {
    ListingType.SELL_COINS: "📤 Продажа bio",
    ListingType.BUY_COINS: "📥 Покупка bio",
    ListingType.HIT_CONTRACT: "🎯 Контракт",
}

_STATUS_LABEL = {
    ListingStatus.ACTIVE: "🟢 Активно",
    ListingStatus.COMPLETED: "✅ Выполнено",
    ListingStatus.CANCELLED: "❌ Отменено",
    ListingStatus.EXPIRED: "⌛ Истекло",
}


def _fmt_listing(item: dict) -> str:
    ltype = item["listing_type"]
    status = _STATUS_LABEL.get(item["status"], "?")
    expires = item["expires_at"].strftime("%d.%m %H:%M") if item.get("expires_at") else "—"

    if ltype == ListingType.SELL_COINS:
        return (
            f"<b>#{item['id']} — Продажа bio_coins</b>\n"
            f"Количество: <b>{item['amount']:,}</b> 🧫\n"
            f"Цена: <b>{item['price']:,}</b> 💎 premium\n"
            f"Статус: {status}\n"
            f"Действует до: {expires} UTC"
        )
    elif ltype == ListingType.BUY_COINS:
        return (
            f"<b>#{item['id']} — Покупка bio_coins</b>\n"
            f"Хочет купить: <b>{item['amount']:,}</b> 🧫\n"
            f"Готов заплатить: <b>{item['price']:,}</b> 💎 premium\n"
            f"Статус: {status}\n"
            f"Действует до: {expires} UTC"
        )
    else:  # HIT_CONTRACT
        claimed = "🟡 Взят исполнителем" if item.get("buyer_id") else "🔴 Свободен"
        return (
            f"<b>#{item['id']} — Контракт на заражение</b>\n"
            f"Цель: <b>@{escape(item.get('target_username') or '???')}</b>\n"
            f"Награда: <b>{item['reward']:,}</b> 🧫 bio\n"
            f"Статус: {claimed}\n"
            f"Действует до: {expires} UTC"
        )


# ---------------------------------------------------------------------------
# Main market menu
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "market_menu")
async def cb_market_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Show black market main menu."""
    await state.clear()
    await callback.message.edit_text(
        "🏴‍☠️ <b>Чёрный рынок</b>\n\n"
        "Торгуй ресурсами с другими игроками или размести контракт на заражение.",
        reply_markup=market_menu_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Listings list (SELL + BUY)
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "market_listings")
async def cb_market_listings(callback: CallbackQuery, session: AsyncSession) -> None:
    await _show_listings(callback, session, page=0)


@router.callback_query(F.data.startswith("market_listings_pg_"))
async def cb_market_listings_page(callback: CallbackQuery, session: AsyncSession) -> None:
    try:
        page = int(callback.data[len("market_listings_pg_"):])
    except ValueError:
        page = 0
    await _show_listings(callback, session, page=max(0, page))


async def _show_listings(
    callback: CallbackQuery, session: AsyncSession, page: int
) -> None:
    listings = await get_active_listings(session, listing_type=None, limit=100)
    # Filter only trade listings (not contracts)
    trade = [
        item for item in listings
        if item["listing_type"] in (ListingType.SELL_COINS, ListingType.BUY_COINS)
    ]

    if not trade:
        await callback.message.edit_text(
            "🏴‍☠️ <b>Торговые предложения</b>\n\n"
            "Пока нет активных предложений. Будь первым!",
            reply_markup=market_listings_kb([], page=0),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    total = len(trade)
    showing_start = page * PAGE_SIZE + 1
    showing_end = min(showing_start + PAGE_SIZE - 1, total)

    await callback.message.edit_text(
        f"🏴‍☠️ <b>Торговые предложения</b>\n\n"
        f"Показано {showing_start}–{showing_end} из {total}.\n"
        "Нажми на предложение, чтобы выполнить его.",
        reply_markup=market_listings_kb(trade, page=page),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Contracts list
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "market_contracts")
async def cb_market_contracts(callback: CallbackQuery, session: AsyncSession) -> None:
    await _show_contracts(callback, session, page=0)


@router.callback_query(F.data.startswith("market_contracts_pg_"))
async def cb_market_contracts_page(callback: CallbackQuery, session: AsyncSession) -> None:
    try:
        page = int(callback.data[len("market_contracts_pg_"):])
    except ValueError:
        page = 0
    await _show_contracts(callback, session, page=max(0, page))


async def _show_contracts(
    callback: CallbackQuery, session: AsyncSession, page: int
) -> None:
    contracts = await get_active_listings(
        session, listing_type=ListingType.HIT_CONTRACT, limit=100
    )

    if not contracts:
        await callback.message.edit_text(
            "🎯 <b>Контракты на заражение</b>\n\n"
            "Пока нет активных контрактов.",
            reply_markup=market_contracts_kb([], page=0),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    total = len(contracts)
    showing_start = page * PAGE_SIZE + 1
    showing_end = min(showing_start + PAGE_SIZE - 1, total)

    await callback.message.edit_text(
        f"🎯 <b>Контракты на заражение</b>\n\n"
        f"Показано {showing_start}–{showing_end} из {total}.\n"
        "🔴 — свободен, 🟡 — взят исполнителем.\n"
        "Нажми на контракт, чтобы взять его.",
        reply_markup=market_contracts_kb(contracts, page=page),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Fulfill a listing (SELL/BUY)
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("market_fulfill_"))
async def cb_market_fulfill(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    try:
        listing_id = int(callback.data[len("market_fulfill_"):])
    except ValueError:
        await callback.answer("❌ Неверный ID.", show_alert=True)
        return

    success, msg = await fulfill_listing(session, callback.from_user.id, listing_id)

    if success:
        await callback.message.edit_text(msg, reply_markup=market_menu_kb(), parse_mode="HTML")
    else:
        await callback.answer(msg, show_alert=True)

    await callback.answer()


# ---------------------------------------------------------------------------
# Claim a hit contract
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("market_claim_"))
async def cb_market_claim(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    try:
        listing_id = int(callback.data[len("market_claim_"):])
    except ValueError:
        await callback.answer("❌ Неверный ID.", show_alert=True)
        return

    success, msg = await claim_hit_contract(session, callback.from_user.id, listing_id)

    if success:
        await callback.message.edit_text(msg, reply_markup=market_menu_kb(), parse_mode="HTML")
    else:
        await callback.answer(msg, show_alert=True)

    await callback.answer()


# ---------------------------------------------------------------------------
# Cancel a listing
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("market_cancel_"))
async def cb_market_cancel(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    try:
        listing_id = int(callback.data[len("market_cancel_"):])
    except ValueError:
        await callback.answer("❌ Неверный ID.", show_alert=True)
        return

    success, msg = await cancel_listing(session, callback.from_user.id, listing_id)

    if success:
        # Refresh my listings
        listings = await get_my_listings(session, callback.from_user.id)
        await callback.message.edit_text(
            f"📋 <b>Мои предложения</b>\n\n{msg}",
            reply_markup=market_my_kb(listings),
            parse_mode="HTML",
        )
    else:
        await callback.answer(msg, show_alert=True)

    await callback.answer()


# ---------------------------------------------------------------------------
# My listings
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "market_my")
async def cb_market_my(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    listings = await get_my_listings(session, callback.from_user.id)

    if not listings:
        await callback.message.edit_text(
            "📋 <b>Мои предложения</b>\n\nУ тебя пока нет предложений.",
            reply_markup=back_button("market_menu"),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    active = sum(1 for item in listings if item["status"] == ListingStatus.ACTIVE)
    await callback.message.edit_text(
        f"📋 <b>Мои предложения</b>\n\n"
        f"Всего: <b>{len(listings)}</b> | Активных: <b>{active}</b>\n\n"
        "Нажми на активное предложение, чтобы отменить его.",
        reply_markup=market_my_kb(listings),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "market_my_noop")
async def cb_market_my_noop(callback: CallbackQuery) -> None:
    """Inactive listing button — just show a tooltip."""
    await callback.answer("Это предложение уже не активно.")


# ---------------------------------------------------------------------------
# Sell flow — FSM: amount → price → create
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "market_sell")
async def cb_market_sell(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(MarketSellStates.waiting_for_amount)
    await callback.message.edit_text(
        "📤 <b>Продажа bio_coins</b>\n\n"
        "Введи количество <b>bio_coins</b>, которое хочешь продать:\n"
        "<i>(Комиссия 5% — удерживается при создании предложения)</i>\n\n"
        "Или нажми «Назад» для отмены:",
        reply_markup=back_button("market_menu"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(MarketSellStates.waiting_for_amount)
async def msg_sell_amount(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    try:
        amount = int(raw)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Введи целое положительное число. Попробуй ещё раз:",
            reply_markup=back_button("market_menu"),
        )
        return

    await state.update_data(sell_amount=amount)
    await state.set_state(MarketSellStates.waiting_for_price)
    await message.answer(
        f"📤 Продаёшь: <b>{amount:,}</b> 🧫 bio\n\n"
        "Теперь введи цену в <b>premium_coins</b> за всё количество:",
        reply_markup=back_button("market_menu"),
        parse_mode="HTML",
    )


@router.message(MarketSellStates.waiting_for_price)
async def msg_sell_price(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    raw = (message.text or "").strip()
    try:
        price = int(raw)
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Введи целое положительное число. Попробуй ещё раз:",
            reply_markup=back_button("market_menu"),
        )
        return

    data = await state.get_data()
    amount = data.get("sell_amount", 0)
    await state.clear()

    success, msg = await create_sell_listing(
        session, message.from_user.id, amount, price
    )
    await message.answer(
        msg,
        reply_markup=market_menu_kb(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Buy flow — FSM: amount → price → create
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "market_buy")
async def cb_market_buy(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(MarketBuyStates.waiting_for_amount)
    await callback.message.edit_text(
        "📥 <b>Покупка bio_coins</b>\n\n"
        "Введи количество <b>bio_coins</b>, которое хочешь купить:\n\n"
        "Или нажми «Назад» для отмены:",
        reply_markup=back_button("market_menu"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(MarketBuyStates.waiting_for_amount)
async def msg_buy_amount(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    try:
        amount = int(raw)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Введи целое положительное число. Попробуй ещё раз:",
            reply_markup=back_button("market_menu"),
        )
        return

    await state.update_data(buy_amount=amount)
    await state.set_state(MarketBuyStates.waiting_for_price)
    await message.answer(
        f"📥 Хочешь купить: <b>{amount:,}</b> 🧫 bio\n\n"
        "Введи цену в <b>premium_coins</b>, которую готов заплатить:",
        reply_markup=back_button("market_menu"),
        parse_mode="HTML",
    )


@router.message(MarketBuyStates.waiting_for_price)
async def msg_buy_price(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    raw = (message.text or "").strip()
    try:
        price = int(raw)
        if price <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Введи целое положительное число. Попробуй ещё раз:",
            reply_markup=back_button("market_menu"),
        )
        return

    data = await state.get_data()
    amount = data.get("buy_amount", 0)
    await state.clear()

    success, msg = await create_buy_listing(
        session, message.from_user.id, amount, price
    )
    await message.answer(
        msg,
        reply_markup=market_menu_kb(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Hit contract creation — FSM: username → reward → create
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "market_create_contract")
async def cb_market_create_contract(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(MarketContractStates.waiting_for_username)
    await callback.message.edit_text(
        "🎯 <b>Создание контракта на заражение</b>\n\n"
        "Введи <b>@username</b> игрока, которого нужно заразить\n"
        "(можно без символа @):\n\n"
        "Или нажми «Назад» для отмены:",
        reply_markup=back_button("market_contracts"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(MarketContractStates.waiting_for_username)
async def msg_contract_username(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    if not raw:
        await message.answer(
            "❌ Username не может быть пустым. Попробуй ещё раз:",
            reply_markup=back_button("market_menu"),
        )
        return

    clean = raw.lstrip("@")
    await state.update_data(contract_target=clean)
    await state.set_state(MarketContractStates.waiting_for_reward)
    await message.answer(
        f"🎯 Цель: <b>@{escape(clean)}</b>\n\n"
        "Введи <b>награду в bio_coins</b> для исполнителя контракта:",
        reply_markup=back_button("market_menu"),
        parse_mode="HTML",
    )


@router.message(MarketContractStates.waiting_for_reward)
async def msg_contract_reward(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    raw = (message.text or "").strip()
    try:
        reward = int(raw)
        if reward <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ Введи целое положительное число. Попробуй ещё раз:",
            reply_markup=back_button("market_menu"),
        )
        return

    data = await state.get_data()
    target = data.get("contract_target", "")
    await state.clear()

    success, msg = await create_hit_contract(
        session, message.from_user.id, target, reward
    )
    await message.answer(
        msg,
        reply_markup=market_menu_kb(),
        parse_mode="HTML",
    )
