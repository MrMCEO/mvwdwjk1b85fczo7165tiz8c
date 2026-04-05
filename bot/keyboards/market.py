"""БиоБиржа keyboards."""

from __future__ import annotations

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.models.market import ListingStatus, ListingType

# Number of listings shown per page
PAGE_SIZE = 5


def market_menu_kb() -> InlineKeyboardMarkup:
    """Root navigation for the БиоБиржа."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📦 Продать предмет",    callback_data="market_sell_item",    style=ButtonStyle.SUCCESS)
    builder.button(text="🧬 Продать мутацию",    callback_data="market_sell_mutation", style=ButtonStyle.SUCCESS)
    builder.button(text="🎯 Контракты",          callback_data="market_contracts",     style=ButtonStyle.PRIMARY)
    builder.button(text="📋 Все лоты",           callback_data="market_listings",      style=ButtonStyle.PRIMARY)
    builder.button(text="🗂 Мои лоты",           callback_data="market_my",            style=ButtonStyle.PRIMARY)
    builder.button(text="◀️ Назад",              callback_data="main_menu")
    builder.adjust(2, 1, 2, 1)
    return builder.as_markup()


def market_listings_kb(listings: list[dict], page: int = 0) -> InlineKeyboardMarkup:
    """
    Paginated list of SELL_ITEM / SELL_MUTATION listings.

    Each listing gets a button with type, goods description and price.
    """
    builder = InlineKeyboardBuilder()

    start = page * PAGE_SIZE
    page_items = listings[start : start + PAGE_SIZE]

    for item in page_items:
        ltype = item["listing_type"]
        if ltype == ListingType.SELL_ITEM:
            label = f"📦 #{item['id']} · Предмет · {item['price']:,} 🧫"
        elif ltype == ListingType.SELL_MUTATION:
            label = f"🧬 #{item['id']} · Мутация · {item['price']:,} 🧫"
        else:
            label = f"📄 #{item['id']} · Лот · {item['price']:,} 🧫"
        builder.button(text=label, callback_data=f"market_buy_{item['id']}", style=ButtonStyle.PRIMARY)

    # Pagination row
    nav_buttons = 0
    if page > 0:
        builder.button(text="◀️ Пред.", callback_data=f"market_listings_pg_{page - 1}", style=ButtonStyle.PRIMARY)
        nav_buttons += 1
    if start + PAGE_SIZE < len(listings):
        builder.button(text="След. ▶️", callback_data=f"market_listings_pg_{page + 1}", style=ButtonStyle.PRIMARY)
        nav_buttons += 1

    builder.button(text="◀️ Назад", callback_data="market_menu")

    row_sizes = [1] * len(page_items)
    if nav_buttons:
        row_sizes.append(nav_buttons)
    row_sizes.append(1)
    builder.adjust(*row_sizes)

    return builder.as_markup()


def market_contracts_kb(contracts: list[dict], page: int = 0) -> InlineKeyboardMarkup:
    """Paginated list of active hit contracts."""
    builder = InlineKeyboardBuilder()

    start = page * PAGE_SIZE
    page_items = contracts[start : start + PAGE_SIZE]

    for item in page_items:
        target = item.get("target_username") or "???"
        claimed = "🔴" if item.get("buyer_id") is None else "🟡"
        label = f"🎯 #{item['id']} · {claimed} @{target} · {item['reward']:,} 🧫"
        builder.button(text=label, callback_data=f"market_claim_{item['id']}", style=ButtonStyle.PRIMARY)

    nav_buttons = 0
    if page > 0:
        builder.button(text="◀️ Пред.", callback_data=f"market_contracts_pg_{page - 1}", style=ButtonStyle.PRIMARY)
        nav_buttons += 1
    if start + PAGE_SIZE < len(contracts):
        builder.button(text="След. ▶️", callback_data=f"market_contracts_pg_{page + 1}", style=ButtonStyle.PRIMARY)
        nav_buttons += 1

    builder.button(text="➕ Создать контракт", callback_data="market_create_contract", style=ButtonStyle.SUCCESS)
    builder.button(text="◀️ Назад",            callback_data="market_menu")

    row_sizes = [1] * len(page_items)
    if nav_buttons:
        row_sizes.append(nav_buttons)
    row_sizes += [1, 1]
    builder.adjust(*row_sizes)

    return builder.as_markup()


def market_listing_detail_kb(listing: dict, is_owner: bool) -> InlineKeyboardMarkup:
    """Detail view of a single listing: buy or cancel."""
    builder = InlineKeyboardBuilder()

    ltype = listing["listing_type"]
    lid = listing["id"]

    if is_owner:
        builder.button(text="❌ Снять с продажи", callback_data=f"market_cancel_{lid}", style=ButtonStyle.DANGER)
    else:
        if ltype in (ListingType.SELL_ITEM, ListingType.SELL_MUTATION):
            builder.button(text="💸 Купить", callback_data=f"market_buy_{lid}", style=ButtonStyle.SUCCESS)
        elif ltype == ListingType.HIT_CONTRACT:
            builder.button(text="🔫 Взять контракт", callback_data=f"market_claim_{lid}", style=ButtonStyle.SUCCESS)

    builder.button(text="◀️ Назад", callback_data="market_menu")
    builder.adjust(1)
    return builder.as_markup()


def market_my_kb(listings: list[dict]) -> InlineKeyboardMarkup:
    """List of the user's own listings with cancel buttons for active ones."""
    builder = InlineKeyboardBuilder()

    for item in listings[:15]:  # cap at 15 for readability
        status_icon = {
            ListingStatus.ACTIVE: "🟢",
            ListingStatus.COMPLETED: "✅",
            ListingStatus.CANCELLED: "❌",
            ListingStatus.EXPIRED: "⌛",
        }.get(item["status"], "❓")

        ltype = item["listing_type"]
        if ltype == ListingType.SELL_ITEM:
            desc = f"Предмет — {item['price']:,}🧫"
        elif ltype == ListingType.SELL_MUTATION:
            desc = f"Мутация — {item['price']:,}🧫"
        elif ltype == ListingType.HIT_CONTRACT:
            desc = f"Контракт @{item.get('target_username', '???')}"
        else:
            desc = f"Лот #{item['id']}"

        label = f"{status_icon} #{item['id']} {desc}"
        if item["status"] == ListingStatus.ACTIVE:
            builder.button(text=label, callback_data=f"market_cancel_{item['id']}", style=ButtonStyle.DANGER)
        else:
            builder.button(text=label, callback_data="market_my_noop")

    builder.button(text="◀️ Назад", callback_data="market_menu")
    builder.adjust(*([1] * min(len(listings), 15)), 1)
    return builder.as_markup()


def market_inventory_items_kb(items: list[dict], page: int = 0) -> InlineKeyboardMarkup:
    """
    Choose an item from inventory to list on the exchange.

    items: list of dicts with keys: id, item_type, emoji, name, description
    """
    builder = InlineKeyboardBuilder()

    start = page * PAGE_SIZE
    page_items = items[start : start + PAGE_SIZE]

    for item in page_items:
        label = f"{item.get('emoji', '📦')} {item['name']}"
        builder.button(text=label, callback_data=f"market_pick_item_{item['id']}")

    nav_buttons = 0
    if page > 0:
        builder.button(text="◀️ Пред.", callback_data=f"market_inv_pg_{page - 1}", style=ButtonStyle.PRIMARY)
        nav_buttons += 1
    if start + PAGE_SIZE < len(items):
        builder.button(text="След. ▶️", callback_data=f"market_inv_pg_{page + 1}", style=ButtonStyle.PRIMARY)
        nav_buttons += 1

    builder.button(text="◀️ Назад", callback_data="market_menu")

    row_sizes = [1] * len(page_items)
    if nav_buttons:
        row_sizes.append(nav_buttons)
    row_sizes.append(1)
    builder.adjust(*row_sizes)

    return builder.as_markup()


def market_inventory_mutations_kb(
    mutations: list[dict], page: int = 0
) -> InlineKeyboardMarkup:
    """
    Choose a mutation from inventory to list on the exchange.

    mutations: list of dicts with keys: id, mutation_type, rarity, description
    """
    builder = InlineKeyboardBuilder()

    start = page * PAGE_SIZE
    page_items = mutations[start : start + PAGE_SIZE]

    for m in page_items:
        label = f"🧬 {m['description']} [{m['rarity']}]"
        builder.button(text=label, callback_data=f"market_pick_mutation_{m['id']}")

    nav_buttons = 0
    if page > 0:
        builder.button(text="◀️ Пред.", callback_data=f"market_mut_pg_{page - 1}", style=ButtonStyle.PRIMARY)
        nav_buttons += 1
    if start + PAGE_SIZE < len(mutations):
        builder.button(text="След. ▶️", callback_data=f"market_mut_pg_{page + 1}", style=ButtonStyle.PRIMARY)
        nav_buttons += 1

    builder.button(text="◀️ Назад", callback_data="market_menu")

    row_sizes = [1] * len(page_items)
    if nav_buttons:
        row_sizes.append(nav_buttons)
    row_sizes.append(1)
    builder.adjust(*row_sizes)

    return builder.as_markup()
