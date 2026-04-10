"""
БиоБиржа handlers — P2P trading of items/mutations and hit contracts.

FSM flows:
  - MarketSellItemStates:     pick_item → waiting_for_price → create
  - MarketSellMutationStates: pick_mutation → waiting_for_price → create
  - MarketContractStates:     waiting_for_username → waiting_for_reward → create
"""

from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.common import back_button
from bot.keyboards.market import (
    PAGE_SIZE,
    market_contracts_kb,
    market_inventory_items_kb,
    market_inventory_mutations_kb,
    market_listings_kb,
    market_menu_kb,
    market_my_kb,
)
from bot.models.item import ITEM_CONFIG, Item
from bot.models.market import ListingStatus, ListingType
from bot.services.market import (
    cancel_listing,
    claim_hit_contract,
    create_hit_contract,
    create_item_listing,
    create_mutation_listing,
    get_active_listings,
    get_my_listings,
    purchase_listing,
)
from bot.services.mutation import MUTATION_CONFIG, get_inventory_mutations
from bot.utils.chat import smart_reply

router = Router(name="market")


# ---------------------------------------------------------------------------
# FSM State groups
# ---------------------------------------------------------------------------


class MarketSellItemStates(StatesGroup):
    waiting_for_price = State()


class MarketSellMutationStates(StatesGroup):
    waiting_for_price = State()


class MarketContractStates(StatesGroup):
    waiting_for_username = State()
    waiting_for_reward = State()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TYPE_LABEL = {
    ListingType.SELL_ITEM: "📦 Продажа предмета",
    ListingType.SELL_MUTATION: "🧬 Продажа мутации",
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

    if ltype == ListingType.SELL_ITEM:
        return (
            f"📦 <b>Лот #{item['id']} — Предмет</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"💰 Цена: <code>{item['price']:,}</code> 🧫\n"
            f"📊 Статус: {status}\n"
            f"⏳ Действует до: <i>{expires} UTC</i>"
        )
    elif ltype == ListingType.SELL_MUTATION:
        return (
            f"🧬 <b>Лот #{item['id']} — Мутация</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"💰 Цена: <code>{item['price']:,}</code> 🧫\n"
            f"📊 Статус: {status}\n"
            f"⏳ Действует до: <i>{expires} UTC</i>"
        )
    else:  # HIT_CONTRACT
        claimed = "🟡 Взят исполнителем" if item.get("buyer_id") else "🔴 Свободен"
        return (
            f"🎯 <b>Контракт #{item['id']} — На заражение</b>\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🎯 Цель: <b>@{escape(item.get('target_username') or '???')}</b>\n"
            f"💰 Награда: <code>{item['reward']:,}</code> 🧫\n"
            f"📊 Статус: {claimed}\n"
            f"⏳ Действует до: <i>{expires} UTC</i>"
        )


# ---------------------------------------------------------------------------
# Main market menu
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "market_menu")
async def cb_market_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Show БиоБиржа main menu."""
    await state.clear()
    await callback.message.edit_text(
        "🔬 <b>БиоБиржа</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "📦 Торгуй предметами и мутациями с другими игроками\n"
        "🎯 Размещай контракты на заражение врагов\n\n"
        "<i>Комиссия биржи: +5% от цены (сверху для покупателя)</i>",
        reply_markup=market_menu_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Listings list (SELL_ITEM + SELL_MUTATION)
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
    # Show only item and mutation listings (not contracts)
    trade = [
        item for item in listings
        if item["listing_type"] in (ListingType.SELL_ITEM, ListingType.SELL_MUTATION)
    ]

    if not trade:
        await callback.message.edit_text(
            "🔬 <b>Все лоты — БиоБиржа</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🕳 Пока нет активных лотов.\n"
            "<i>Будь первым — выставь что-нибудь на продажу!</i>",
            reply_markup=market_listings_kb([], page=0),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    total = len(trade)
    showing_start = page * PAGE_SIZE + 1
    showing_end = min(showing_start + PAGE_SIZE - 1, total)

    await callback.message.edit_text(
        f"🔬 <b>Все лоты — БиоБиржа</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 Показано <code>{showing_start}–{showing_end}</code> из <code>{total}</code>\n"
        f"<i>Нажми на лот, чтобы купить</i>",
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
            "🎯 <b>Контракты на заражение</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🕳 Пока нет активных контрактов.\n"
            "<i>Размести первый контракт и найди исполнителя!</i>",
            reply_markup=market_contracts_kb([], page=0),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    total = len(contracts)
    showing_start = page * PAGE_SIZE + 1
    showing_end = min(showing_start + PAGE_SIZE - 1, total)

    await callback.message.edit_text(
        f"🎯 <b>Контракты на заражение</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📋 Показано <code>{showing_start}–{showing_end}</code> из <code>{total}</code>\n"
        f"🔴 — свободен  🟡 — взят исполнителем\n"
        f"<i>Нажми на контракт, чтобы взяться за него</i>",
        reply_markup=market_contracts_kb(contracts, page=page),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Purchase a listing
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("market_buy_"))
async def cb_market_buy(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    try:
        listing_id = int(callback.data[len("market_buy_"):])
    except ValueError:
        await callback.answer("❌ Неверный ID.", show_alert=True)
        return

    # Acknowledge immediately to prevent query timeout
    await callback.answer()

    success, msg = await purchase_listing(session, callback.from_user.id, listing_id)

    if success:
        await callback.message.edit_text(msg, reply_markup=market_menu_kb(), parse_mode="HTML")
    else:
        await callback.message.edit_text(
            f"❌ {msg}", reply_markup=market_menu_kb(), parse_mode="HTML"
        )


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

    # Acknowledge immediately to prevent query timeout
    await callback.answer()

    success, msg = await claim_hit_contract(session, callback.from_user.id, listing_id)

    if success:
        await callback.message.edit_text(msg, reply_markup=market_menu_kb(), parse_mode="HTML")
    else:
        await callback.message.edit_text(
            f"❌ {msg}", reply_markup=market_menu_kb(), parse_mode="HTML"
        )


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

    # Acknowledge immediately to prevent query timeout
    await callback.answer()

    success, msg = await cancel_listing(session, callback.from_user.id, listing_id)

    if success:
        listings = await get_my_listings(session, callback.from_user.id)
        await callback.message.edit_text(
            f"📋 <b>Мои лоты</b>\n\n{msg}",
            reply_markup=market_my_kb(listings),
            parse_mode="HTML",
        )
    else:
        await callback.message.edit_text(
            f"❌ {msg}", reply_markup=back_button("market_my"), parse_mode="HTML"
        )


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
            "📋 <b>Мои лоты</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "🕳 У тебя пока нет лотов.\n"
            "<i>Продай предмет или мутацию через главное меню биржи</i>",
            reply_markup=back_button("market_menu"),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    active = sum(1 for item in listings if item["status"] == ListingStatus.ACTIVE)
    total = len(listings)
    await callback.message.edit_text(
        f"📋 <b>Мои лоты</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 Всего: <code>{total}</code>  🟢 Активных: <code>{active}</code>\n\n"
        f"<i>Нажми на 🟢 активный лот, чтобы снять с продажи</i>",
        reply_markup=market_my_kb(listings),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "market_my_noop")
async def cb_market_my_noop(callback: CallbackQuery) -> None:
    """Inactive listing button — just show a tooltip."""
    await callback.answer("Этот лот уже не активен.")


# ---------------------------------------------------------------------------
# Sell item flow — pick item → set price → create listing
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "market_sell_item")
async def cb_market_sell_item(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    """Show player's unused items for selection."""
    await state.clear()

    # Fetch all unused items owned by the player
    result = await session.execute(
        select(Item).where(
            and_(
                Item.owner_id == callback.from_user.id,
                Item.is_used == False,  # noqa: E712
            )
        ).order_by(Item.item_type, Item.id)
    )
    items = list(result.scalars().all())

    if not items:
        await callback.message.edit_text(
            "📦 <b>Продать предмет</b>\n\n"
            "У тебя нет предметов в инвентаре.\n"
            "Создай предметы в 🔬 Лаборатории.",
            reply_markup=back_button("market_menu"),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    items_data = []
    for item in items:
        cfg = ITEM_CONFIG.get(item.item_type, {})
        items_data.append({
            "id": item.id,
            "item_type": item.item_type,
            "name": cfg.get("name", item.item_type.value),
            "emoji": cfg.get("emoji", "📦"),
            "description": cfg.get("desc", ""),
        })

    await callback.message.edit_text(
        "📦 <b>Продать предмет</b>\n\n"
        "Выбери предмет из инвентаря для продажи на 🔬 БиоБирже:",
        reply_markup=market_inventory_items_kb(items_data, page=0),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("market_inv_pg_"))
async def cb_market_inv_page(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Pagination for item selection."""
    try:
        page = int(callback.data[len("market_inv_pg_"):])
    except ValueError:
        page = 0

    result = await session.execute(
        select(Item).where(
            and_(
                Item.owner_id == callback.from_user.id,
                Item.is_used == False,  # noqa: E712
            )
        ).order_by(Item.item_type, Item.id)
    )
    items = list(result.scalars().all())
    items_data = []
    for item in items:
        cfg = ITEM_CONFIG.get(item.item_type, {})
        items_data.append({
            "id": item.id,
            "item_type": item.item_type,
            "name": cfg.get("name", item.item_type.value),
            "emoji": cfg.get("emoji", "📦"),
            "description": cfg.get("desc", ""),
        })

    await callback.message.edit_reply_markup(
        reply_markup=market_inventory_items_kb(items_data, page=max(0, page))
    )
    await callback.answer()


@router.callback_query(F.data.startswith("market_pick_item_"))
async def cb_market_pick_item(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Item selected — ask for price."""
    try:
        item_id = int(callback.data[len("market_pick_item_"):])
    except ValueError:
        await callback.answer("❌ Неверный ID.", show_alert=True)
        return

    # Acknowledge immediately to prevent query timeout
    await callback.answer()

    # Verify ownership
    result = await session.execute(
        select(Item).where(
            and_(
                Item.id == item_id,
                Item.owner_id == callback.from_user.id,
                Item.is_used == False,  # noqa: E712
            )
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        await callback.message.edit_text(
            "❌ Предмет не найден.",
            reply_markup=back_button("market_menu"),
            parse_mode="HTML",
        )
        return

    cfg = ITEM_CONFIG.get(item.item_type, {})
    item_name = cfg.get("name", item.item_type.value)
    item_emoji = cfg.get("emoji", "📦")

    await state.set_state(MarketSellItemStates.waiting_for_price)
    await state.update_data(selected_item_id=item_id, item_name=item_name, item_emoji=item_emoji)

    await callback.message.edit_text(
        f"📦 Выбран: {item_emoji} <b>{item_name}</b>\n\n"
        "Введи цену в <b>🧫 BioCoins</b> (покупатель заплатит +5% комиссии):\n\n"
        "Или нажми «Назад» для отмены:",
        reply_markup=back_button("market_menu"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(MarketSellItemStates.waiting_for_price)
async def msg_sell_item_price(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    raw = (message.text or "").strip()
    try:
        price = int(raw)
        if price <= 0:
            raise ValueError
    except ValueError:
        await smart_reply(
            message,
            "❌ Введи целое положительное число. Попробуй ещё раз:",
            reply_markup=back_button("market_menu"),
        )
        return

    data = await state.get_data()
    item_id = data.get("selected_item_id")
    await state.clear()

    if item_id is None:
        await smart_reply(message, "❌ Произошла ошибка. Начни заново.", reply_markup=market_menu_kb())
        return

    success, msg = await create_item_listing(session, message.from_user.id, item_id, price)
    await smart_reply(message, msg, reply_markup=market_menu_kb())


# ---------------------------------------------------------------------------
# Sell mutation flow — pick mutation → set price → create listing
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "market_sell_mutation")
async def cb_market_sell_mutation(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    """Show player's inventory mutations for selection."""
    await state.clear()

    mutations = await get_inventory_mutations(session, callback.from_user.id)

    if not mutations:
        await callback.message.edit_text(
            "🧬 <b>Продать мутацию</b>\n\n"
            "У тебя нет мутаций в инвентаре.\n"
            "Мутации появляются после атак (15% шанс).",
            reply_markup=back_button("market_menu"),
            parse_mode="HTML",
        )
        await callback.answer()
        return

    mutations_data = []
    for m in mutations:
        cfg = MUTATION_CONFIG.get(m.mutation_type, {})
        mutations_data.append({
            "id": m.id,
            "mutation_type": m.mutation_type,
            "rarity": m.rarity.value,
            "description": cfg.get("description", m.mutation_type.value),
        })

    await callback.message.edit_text(
        "🧬 <b>Продать мутацию</b>\n\n"
        "Выбери мутацию из инвентаря для продажи на 🔬 БиоБирже:",
        reply_markup=market_inventory_mutations_kb(mutations_data, page=0),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data.startswith("market_mut_pg_"))
async def cb_market_mut_page(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Pagination for mutation selection."""
    try:
        page = int(callback.data[len("market_mut_pg_"):])
    except ValueError:
        page = 0

    mutations = await get_inventory_mutations(session, callback.from_user.id)
    mutations_data = []
    for m in mutations:
        cfg = MUTATION_CONFIG.get(m.mutation_type, {})
        mutations_data.append({
            "id": m.id,
            "mutation_type": m.mutation_type,
            "rarity": m.rarity.value,
            "description": cfg.get("description", m.mutation_type.value),
        })

    await callback.message.edit_reply_markup(
        reply_markup=market_inventory_mutations_kb(mutations_data, page=max(0, page))
    )
    await callback.answer()


@router.callback_query(F.data.startswith("market_pick_mutation_"))
async def cb_market_pick_mutation(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Mutation selected — ask for price."""
    try:
        mutation_id = int(callback.data[len("market_pick_mutation_"):])
    except ValueError:
        await callback.answer("❌ Неверный ID.", show_alert=True)
        return

    # Acknowledge immediately to prevent query timeout
    await callback.answer()

    # Verify it's in inventory and owned by player
    mutations = await get_inventory_mutations(session, callback.from_user.id)
    mutation = next((m for m in mutations if m.id == mutation_id), None)
    if mutation is None:
        await callback.message.edit_text(
            "❌ Мутация не найдена.",
            reply_markup=back_button("market_menu"),
            parse_mode="HTML",
        )
        return

    cfg = MUTATION_CONFIG.get(mutation.mutation_type, {})
    description = cfg.get("description", mutation.mutation_type.value)
    rarity = mutation.rarity.value

    await state.set_state(MarketSellMutationStates.waiting_for_price)
    await state.update_data(
        selected_mutation_id=mutation_id,
        mutation_description=description,
        mutation_rarity=rarity,
    )

    await callback.message.edit_text(
        f"🧬 Выбрана: <b>{description}</b> [{rarity}]\n\n"
        "Введи цену в <b>🧫 BioCoins</b> (покупатель заплатит +5% комиссии):\n\n"
        "Или нажми «Назад» для отмены:",
        reply_markup=back_button("market_menu"),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(MarketSellMutationStates.waiting_for_price)
async def msg_sell_mutation_price(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    raw = (message.text or "").strip()
    try:
        price = int(raw)
        if price <= 0:
            raise ValueError
    except ValueError:
        await smart_reply(
            message,
            "❌ Введи целое положительное число. Попробуй ещё раз:",
            reply_markup=back_button("market_menu"),
        )
        return

    data = await state.get_data()
    mutation_id = data.get("selected_mutation_id")
    await state.clear()

    if mutation_id is None:
        await smart_reply(message, "❌ Произошла ошибка. Начни заново.", reply_markup=market_menu_kb())
        return

    success, msg = await create_mutation_listing(
        session, message.from_user.id, mutation_id, price
    )
    await smart_reply(message, msg, reply_markup=market_menu_kb())


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
        await smart_reply(
            message,
            "❌ Username не может быть пустым. Попробуй ещё раз:",
            reply_markup=back_button("market_menu"),
        )
        return

    clean = raw.lstrip("@")
    await state.update_data(contract_target=clean)
    await state.set_state(MarketContractStates.waiting_for_reward)
    await smart_reply(
        message,
        f"🎯 Цель: <b>@{escape(clean)}</b>\n\n"
        "Введи <b>награду в 🧫 BioCoins</b> для исполнителя контракта:",
        reply_markup=back_button("market_menu"),
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
        await smart_reply(
            message,
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
    await smart_reply(
        message,
        msg,
        reply_markup=market_menu_kb(),
    )
