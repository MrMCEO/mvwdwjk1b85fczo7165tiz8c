"""
Unit tests for bot/services/market.py
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.market import ListingStatus, ListingType, MarketListing
from bot.models.user import User
from bot.services.market import (
    SELL_COMMISSION_PCT,
    cancel_listing,
    create_hit_contract,
    create_sell_listing,
    fulfill_listing,
)
from bot.services.player import create_player


async def _give_bio(session: AsyncSession, tg_id: int, amount: int) -> None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = result.scalar_one()
    user.bio_coins = amount
    await session.flush()


async def _give_premium(session: AsyncSession, tg_id: int, amount: int) -> None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = result.scalar_one()
    user.premium_coins = amount
    await session.flush()


async def test_create_sell_listing(session: AsyncSession):
    """Seller with enough coins creates a SELL listing and coins are deducted."""
    await create_player(session, tg_id=8001, username="seller1")
    await _give_bio(session, 8001, 1000)

    ok, msg = await create_sell_listing(
        session, seller_id=8001, bio_amount=100, premium_price=10
    )
    assert ok is True
    assert "Предложение" in msg

    # Commission = max(1, round(100 * 0.05)) = 5; total frozen = 105
    result = await session.execute(select(User).where(User.tg_id == 8001))
    user = result.scalar_one()
    commission = max(1, round(100 * SELL_COMMISSION_PCT))
    assert user.bio_coins == 1000 - 100 - commission


async def test_create_sell_listing_not_enough_coins(session: AsyncSession):
    """Seller without enough coins receives an error."""
    await create_player(session, tg_id=8002, username="seller2")
    # bio_coins = 0

    ok, msg = await create_sell_listing(
        session, seller_id=8002, bio_amount=500, premium_price=50
    )
    assert ok is False
    assert "Недостаточно" in msg


async def test_fulfill_listing(session: AsyncSession):
    """Buyer with enough premium_coins fulfills a SELL listing."""
    await create_player(session, tg_id=8010, username="seller10")
    await create_player(session, tg_id=8011, username="buyer11")
    await _give_bio(session, 8010, 500)
    await _give_premium(session, 8011, 100)

    ok_create, _ = await create_sell_listing(
        session, seller_id=8010, bio_amount=100, premium_price=10
    )
    assert ok_create is True

    # Find the listing id
    result = await session.execute(
        select(MarketListing).where(MarketListing.seller_id == 8010)
    )
    listing = result.scalar_one()

    ok_fulfill, msg = await fulfill_listing(
        session, fulfiller_id=8011, listing_id=listing.id
    )
    assert ok_fulfill is True
    assert "выполнена" in msg

    await session.refresh(listing)
    assert listing.status == ListingStatus.COMPLETED


async def test_fulfill_own_listing(session: AsyncSession):
    """A seller cannot fulfill their own listing."""
    await create_player(session, tg_id=8020, username="seller20")
    await _give_bio(session, 8020, 500)

    await create_sell_listing(
        session, seller_id=8020, bio_amount=100, premium_price=10
    )

    result = await session.execute(
        select(MarketListing).where(MarketListing.seller_id == 8020)
    )
    listing = result.scalar_one()

    ok, msg = await fulfill_listing(
        session, fulfiller_id=8020, listing_id=listing.id
    )
    assert ok is False
    assert "собственное" in msg


async def test_cancel_listing(session: AsyncSession):
    """Seller can cancel their listing and receive a refund."""
    await create_player(session, tg_id=8030, username="seller30")
    await _give_bio(session, 8030, 1000)

    commission = max(1, round(200 * SELL_COMMISSION_PCT))
    total_frozen = 200 + commission

    ok_create, _ = await create_sell_listing(
        session, seller_id=8030, bio_amount=200, premium_price=20
    )
    assert ok_create is True

    result = await session.execute(
        select(MarketListing).where(MarketListing.seller_id == 8030)
    )
    listing = result.scalar_one()

    ok_cancel, msg = await cancel_listing(
        session, user_id=8030, listing_id=listing.id
    )
    assert ok_cancel is True
    assert "отменено" in msg

    await session.refresh(listing)
    assert listing.status == ListingStatus.CANCELLED

    # Balance restored
    result = await session.execute(select(User).where(User.tg_id == 8030))
    user = result.scalar_one()
    assert user.bio_coins == 1000  # full refund including commission


async def test_cancel_listing_not_owner(session: AsyncSession):
    """Only the listing creator can cancel it."""
    await create_player(session, tg_id=8040, username="seller40")
    await create_player(session, tg_id=8041, username="other41")
    await _give_bio(session, 8040, 500)

    await create_sell_listing(
        session, seller_id=8040, bio_amount=100, premium_price=10
    )

    result = await session.execute(
        select(MarketListing).where(MarketListing.seller_id == 8040)
    )
    listing = result.scalar_one()

    ok, msg = await cancel_listing(
        session, user_id=8041, listing_id=listing.id
    )
    assert ok is False
    assert "своё" in msg


async def test_create_hit_contract(session: AsyncSession):
    """Client can place a hit contract on another player."""
    await create_player(session, tg_id=8050, username="client50")
    await create_player(session, tg_id=8051, username="target51")
    await _give_bio(session, 8050, 500)

    ok, msg = await create_hit_contract(
        session, client_id=8050, target_username="target51", reward_bio=200
    )
    assert ok is True
    assert "Контракт" in msg
    assert "target51" in msg

    result = await session.execute(select(User).where(User.tg_id == 8050))
    user = result.scalar_one()
    assert user.bio_coins == 300


async def test_create_hit_contract_self(session: AsyncSession):
    """Creating a hit contract on yourself fails."""
    await create_player(session, tg_id=8060, username="self60")
    await _give_bio(session, 8060, 500)

    ok, msg = await create_hit_contract(
        session, client_id=8060, target_username="self60", reward_bio=100
    )
    assert ok is False
    assert "самого себя" in msg


async def test_create_hit_contract_not_enough_coins(session: AsyncSession):
    """Placing a hit contract without enough coins fails."""
    await create_player(session, tg_id=8070, username="broke70")
    await create_player(session, tg_id=8071, username="tgt71")

    ok, msg = await create_hit_contract(
        session, client_id=8070, target_username="tgt71", reward_bio=999
    )
    assert ok is False
    assert "Недостаточно" in msg
