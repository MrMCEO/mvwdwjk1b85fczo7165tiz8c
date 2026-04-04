"""Black market keyboards."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.models.market import ListingStatus, ListingType

# Number of listings shown per page
PAGE_SIZE = 5


def market_menu_kb() -> InlineKeyboardMarkup:
    """Root navigation for the black market."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🧫 Купить/Продать BioCoins",  callback_data="market_listings")
    builder.button(text="🎯 Контракты",            callback_data="market_contracts")
    builder.button(text="📋 Мои предложения",      callback_data="market_my")
    builder.button(text="◀️ Назад",               callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def market_listings_kb(listings: list[dict], page: int = 0) -> InlineKeyboardMarkup:
    """
    Paginated list of SELL/BUY listings.

    Each listing gets a button: "[#id] Продаёт 500 bio за 10💎" or similar.
    """
    builder = InlineKeyboardBuilder()

    start = page * PAGE_SIZE
    page_items = listings[start : start + PAGE_SIZE]

    for item in page_items:
        ltype = item["listing_type"]
        if ltype == ListingType.SELL_COINS:
            label = f"[#{item['id']}] 📤 Продаёт {item['amount']:,}🧫 за {item['price']:,}💎"
        else:
            label = f"[#{item['id']}] 📥 Купит {item['amount']:,}🧫 за {item['price']:,}💎"
        builder.button(text=label, callback_data=f"market_fulfill_{item['id']}")

    # Pagination row
    nav_buttons = 0
    if page > 0:
        builder.button(text="◀️ Пред.", callback_data=f"market_listings_pg_{page - 1}")
        nav_buttons += 1
    if start + PAGE_SIZE < len(listings):
        builder.button(text="След. ▶️", callback_data=f"market_listings_pg_{page + 1}")
        nav_buttons += 1

    builder.button(text="➕ Продать 🧫",  callback_data="market_sell")
    builder.button(text="➕ Купить 🧫",   callback_data="market_buy")
    builder.button(text="◀️ Назад",        callback_data="market_menu")

    # Layout: each listing on its own row, nav row, then action buttons 2-wide, back full-width
    row_sizes = [1] * len(page_items)
    if nav_buttons:
        row_sizes.append(nav_buttons)
    row_sizes += [2, 1]
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
        label = f"[#{item['id']}] {claimed} @{target} — {item['reward']:,}🧫"
        builder.button(text=label, callback_data=f"market_claim_{item['id']}")

    nav_buttons = 0
    if page > 0:
        builder.button(text="◀️ Пред.", callback_data=f"market_contracts_pg_{page - 1}")
        nav_buttons += 1
    if start + PAGE_SIZE < len(contracts):
        builder.button(text="След. ▶️", callback_data=f"market_contracts_pg_{page + 1}")
        nav_buttons += 1

    builder.button(text="➕ Создать контракт", callback_data="market_create_contract")
    builder.button(text="◀️ Назад",            callback_data="market_menu")

    row_sizes = [1] * len(page_items)
    if nav_buttons:
        row_sizes.append(nav_buttons)
    row_sizes += [1, 1]
    builder.adjust(*row_sizes)

    return builder.as_markup()


def market_listing_detail_kb(listing: dict, is_owner: bool) -> InlineKeyboardMarkup:
    """Detail view of a single listing: fulfill or cancel."""
    builder = InlineKeyboardBuilder()

    ltype = listing["listing_type"]
    lid = listing["id"]

    if is_owner:
        builder.button(text="❌ Отменить", callback_data=f"market_cancel_{lid}")
    else:
        if ltype == ListingType.SELL_COINS:
            builder.button(text="💸 Купить", callback_data=f"market_fulfill_{lid}")
        elif ltype == ListingType.BUY_COINS:
            builder.button(text="💸 Продать", callback_data=f"market_fulfill_{lid}")
        elif ltype == ListingType.HIT_CONTRACT:
            builder.button(text="🔫 Взять контракт", callback_data=f"market_claim_{lid}")

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
        if ltype == ListingType.SELL_COINS:
            desc = f"Продажа {item['amount']:,}🧫"
        elif ltype == ListingType.BUY_COINS:
            desc = f"Покупка {item['amount']:,}🧫"
        else:
            desc = f"Контракт @{item.get('target_username', '???')}"

        label = f"{status_icon} #{item['id']} {desc}"
        if item["status"] == ListingStatus.ACTIVE:
            builder.button(text=label, callback_data=f"market_cancel_{item['id']}")
        else:
            builder.button(text=label, callback_data="market_my_noop")

    builder.button(text="◀️ Назад", callback_data="market_menu")
    # Each item on its own row, back button last
    builder.adjust(*([1] * min(len(listings), 15)), 1)
    return builder.as_markup()
