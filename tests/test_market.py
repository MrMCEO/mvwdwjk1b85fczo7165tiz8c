"""
Unit tests for bot/services/market.py (БиоБиржа)
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.item import Item, ItemType
from bot.models.market import ListingStatus, ListingType, MarketListing
from bot.models.mutation import Mutation, MutationRarity, MutationType
from bot.models.user import User
from bot.services.market import (
    SELL_COMMISSION_PCT,
    cancel_listing,
    create_hit_contract,
    create_item_listing,
    create_mutation_listing,
    purchase_listing,
)
from bot.services.player import create_player


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _give_bio(session: AsyncSession, tg_id: int, amount: int) -> None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = result.scalar_one()
    user.bio_coins = amount
    await session.flush()


async def _create_item(session: AsyncSession, owner_id: int) -> Item:
    item = Item(owner_id=owner_id, item_type=ItemType.VACCINE)
    session.add(item)
    await session.flush()
    return item


async def _create_inventory_mutation(session: AsyncSession, owner_id: int) -> Mutation:
    """Create a buff mutation in inventory (is_active=False)."""
    m = Mutation(
        owner_id=owner_id,
        mutation_type=MutationType.TOXIC_SPIKE,
        rarity=MutationRarity.COMMON,
        effect_value=0.30,
        duration_hours=6.0,
        is_active=False,
        is_used=False,
    )
    session.add(m)
    await session.flush()
    return m


# ---------------------------------------------------------------------------
# SELL_ITEM tests
# ---------------------------------------------------------------------------


async def test_create_item_listing(session: AsyncSession):
    """Seller creates an item listing successfully."""
    await create_player(session, tg_id=8001, username="seller1")
    item = await _create_item(session, owner_id=8001)

    ok, msg = await create_item_listing(session, seller_id=8001, item_id=item.id, price=100)
    assert ok is True
    assert "Лот" in msg
    assert "100" in msg

    # Listing should exist as ACTIVE
    result = await session.execute(
        select(MarketListing).where(MarketListing.seller_id == 8001)
    )
    listing = result.scalar_one()
    assert listing.listing_type == ListingType.SELL_ITEM
    assert listing.status == ListingStatus.ACTIVE
    assert listing.item_id == item.id


async def test_create_item_listing_zero_price(session: AsyncSession):
    """Price of zero is rejected."""
    await create_player(session, tg_id=8002, username="seller2")
    item = await _create_item(session, owner_id=8002)

    ok, msg = await create_item_listing(session, seller_id=8002, item_id=item.id, price=0)
    assert ok is False
    assert "Цена" in msg


async def test_create_item_listing_wrong_owner(session: AsyncSession):
    """Cannot list item owned by another player."""
    await create_player(session, tg_id=8003, username="seller3")
    await create_player(session, tg_id=8004, username="other4")
    item = await _create_item(session, owner_id=8004)

    ok, msg = await create_item_listing(session, seller_id=8003, item_id=item.id, price=100)
    assert ok is False
    assert "не найден" in msg.lower() or "Предмет" in msg


async def test_purchase_item_listing(session: AsyncSession):
    """Buyer purchases an item listing; ownership transfers, bio_coins deducted."""
    await create_player(session, tg_id=8010, username="seller10")
    await create_player(session, tg_id=8011, username="buyer11")
    item = await _create_item(session, owner_id=8010)
    await _give_bio(session, 8011, 500)

    price = 100
    ok_create, _ = await create_item_listing(session, seller_id=8010, item_id=item.id, price=price)
    assert ok_create is True

    result = await session.execute(
        select(MarketListing).where(MarketListing.seller_id == 8010)
    )
    listing = result.scalar_one()

    ok_buy, msg = await purchase_listing(session, buyer_id=8011, listing_id=listing.id)
    assert ok_buy is True
    assert "Покупка" in msg

    await session.refresh(listing)
    assert listing.status == ListingStatus.COMPLETED
    assert listing.buyer_id == 8011

    # Item ownership transferred
    await session.refresh(item)
    assert item.owner_id == 8011

    # Buyer paid price + 5% commission
    commission = max(1, round(price * SELL_COMMISSION_PCT))
    result = await session.execute(select(User).where(User.tg_id == 8011))
    buyer = result.scalar_one()
    assert buyer.bio_coins == 500 - price - commission

    # Seller received the price
    result = await session.execute(select(User).where(User.tg_id == 8010))
    seller = result.scalar_one()
    assert seller.bio_coins == price


async def test_purchase_own_listing(session: AsyncSession):
    """A seller cannot buy their own listing."""
    await create_player(session, tg_id=8020, username="seller20")
    item = await _create_item(session, owner_id=8020)
    await _give_bio(session, 8020, 500)

    await create_item_listing(session, seller_id=8020, item_id=item.id, price=100)
    result = await session.execute(
        select(MarketListing).where(MarketListing.seller_id == 8020)
    )
    listing = result.scalar_one()

    ok, msg = await purchase_listing(session, buyer_id=8020, listing_id=listing.id)
    assert ok is False
    assert "собственный" in msg.lower() or "Нельзя" in msg


async def test_purchase_not_enough_bio(session: AsyncSession):
    """Buyer without enough bio_coins is rejected."""
    await create_player(session, tg_id=8030, username="seller30")
    await create_player(session, tg_id=8031, username="buyer31")
    item = await _create_item(session, owner_id=8030)
    # buyer has 0 bio_coins by default

    await create_item_listing(session, seller_id=8030, item_id=item.id, price=500)
    result = await session.execute(
        select(MarketListing).where(MarketListing.seller_id == 8030)
    )
    listing = result.scalar_one()

    ok, msg = await purchase_listing(session, buyer_id=8031, listing_id=listing.id)
    assert ok is False
    assert "Недостаточно" in msg


# ---------------------------------------------------------------------------
# SELL_MUTATION tests
# ---------------------------------------------------------------------------


async def test_create_mutation_listing(session: AsyncSession):
    """Seller creates a mutation listing successfully."""
    await create_player(session, tg_id=8040, username="seller40")
    m = await _create_inventory_mutation(session, owner_id=8040)

    ok, msg = await create_mutation_listing(
        session, seller_id=8040, mutation_id=m.id, price=200
    )
    assert ok is True
    assert "Лот" in msg

    result = await session.execute(
        select(MarketListing).where(MarketListing.seller_id == 8040)
    )
    listing = result.scalar_one()
    assert listing.listing_type == ListingType.SELL_MUTATION
    assert listing.mutation_id == m.id


async def test_create_mutation_listing_active_rejected(session: AsyncSession):
    """Cannot list an already-active mutation."""
    await create_player(session, tg_id=8041, username="seller41")
    m = Mutation(
        owner_id=8041,
        mutation_type=MutationType.TOXIC_SPIKE,
        rarity=MutationRarity.COMMON,
        effect_value=0.30,
        duration_hours=6.0,
        is_active=True,   # already active!
        is_used=False,
    )
    session.add(m)
    await session.flush()

    ok, msg = await create_mutation_listing(
        session, seller_id=8041, mutation_id=m.id, price=200
    )
    assert ok is False
    assert "не найдена" in msg.lower() or "активирована" in msg


async def test_purchase_mutation_listing(session: AsyncSession):
    """Buyer purchases a mutation; ownership transfers."""
    await create_player(session, tg_id=8050, username="seller50")
    await create_player(session, tg_id=8051, username="buyer51")
    m = await _create_inventory_mutation(session, owner_id=8050)
    await _give_bio(session, 8051, 1000)

    price = 300
    await create_mutation_listing(session, seller_id=8050, mutation_id=m.id, price=price)
    result = await session.execute(
        select(MarketListing).where(MarketListing.seller_id == 8050)
    )
    listing = result.scalar_one()

    ok, msg = await purchase_listing(session, buyer_id=8051, listing_id=listing.id)
    assert ok is True

    await session.refresh(m)
    assert m.owner_id == 8051

    commission = max(1, round(price * SELL_COMMISSION_PCT))
    result = await session.execute(select(User).where(User.tg_id == 8051))
    buyer = result.scalar_one()
    assert buyer.bio_coins == 1000 - price - commission


# ---------------------------------------------------------------------------
# Cancel listing tests
# ---------------------------------------------------------------------------


async def test_cancel_item_listing(session: AsyncSession):
    """Seller can cancel an item listing (no funds frozen, just unlocked)."""
    await create_player(session, tg_id=8060, username="seller60")
    item = await _create_item(session, owner_id=8060)

    await create_item_listing(session, seller_id=8060, item_id=item.id, price=100)
    result = await session.execute(
        select(MarketListing).where(MarketListing.seller_id == 8060)
    )
    listing = result.scalar_one()

    ok, msg = await cancel_listing(session, user_id=8060, listing_id=listing.id)
    assert ok is True
    assert "отменён" in msg.lower() or "Лот" in msg

    await session.refresh(listing)
    assert listing.status == ListingStatus.CANCELLED


async def test_cancel_listing_not_owner(session: AsyncSession):
    """Only the listing creator can cancel it."""
    await create_player(session, tg_id=8070, username="seller70")
    await create_player(session, tg_id=8071, username="other71")
    item = await _create_item(session, owner_id=8070)

    await create_item_listing(session, seller_id=8070, item_id=item.id, price=100)
    result = await session.execute(
        select(MarketListing).where(MarketListing.seller_id == 8070)
    )
    listing = result.scalar_one()

    ok, msg = await cancel_listing(session, user_id=8071, listing_id=listing.id)
    assert ok is False
    assert "свой" in msg.lower() or "своё" in msg.lower() or "Нельзя" in msg


# ---------------------------------------------------------------------------
# Hit contract tests (unchanged)
# ---------------------------------------------------------------------------


async def test_create_hit_contract(session: AsyncSession):
    """Client can place a hit contract on another player."""
    await create_player(session, tg_id=8080, username="client80")
    await create_player(session, tg_id=8081, username="target81")
    await _give_bio(session, 8080, 500)

    ok, msg = await create_hit_contract(
        session, client_id=8080, target_username="target81", reward_bio=200
    )
    assert ok is True
    assert "Контракт" in msg
    assert "target81" in msg

    result = await session.execute(select(User).where(User.tg_id == 8080))
    user = result.scalar_one()
    assert user.bio_coins == 300


async def test_create_hit_contract_self(session: AsyncSession):
    """Creating a hit contract on yourself fails."""
    await create_player(session, tg_id=8090, username="self90")
    await _give_bio(session, 8090, 500)

    ok, msg = await create_hit_contract(
        session, client_id=8090, target_username="self90", reward_bio=100
    )
    assert ok is False
    assert "самого себя" in msg


async def test_create_hit_contract_not_enough_coins(session: AsyncSession):
    """Placing a hit contract without enough coins fails."""
    await create_player(session, tg_id=8100, username="broke100")
    await create_player(session, tg_id=8101, username="tgt101")

    ok, msg = await create_hit_contract(
        session, client_id=8100, target_username="tgt101", reward_bio=999
    )
    assert ok is False
    assert "Недостаточно" in msg


async def test_cancel_hit_contract_refunds(session: AsyncSession):
    """Cancelling a hit contract refunds the reward to the client."""
    await create_player(session, tg_id=8110, username="client110")
    await create_player(session, tg_id=8111, username="target111")
    await _give_bio(session, 8110, 500)

    await create_hit_contract(
        session, client_id=8110, target_username="target111", reward_bio=200
    )

    result = await session.execute(
        select(MarketListing).where(MarketListing.seller_id == 8110)
    )
    listing = result.scalar_one()

    ok, msg = await cancel_listing(session, user_id=8110, listing_id=listing.id)
    assert ok is True
    assert "200" in msg or "наград" in msg

    result = await session.execute(select(User).where(User.tg_id == 8110))
    user = result.scalar_one()
    assert user.bio_coins == 500  # full refund
