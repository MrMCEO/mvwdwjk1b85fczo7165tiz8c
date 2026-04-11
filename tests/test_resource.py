"""
Unit tests for bot/services/resource.py
"""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.resource import (
    Currency,
    ResourceTransaction,
    TransactionReason,
)
from bot.services.player import create_player
from bot.services.resource import (
    DAILY_STREAK_BONUS,
    claim_daily_bonus,
    get_balance,
    mine_resources,
)


async def test_mine_resources(session: AsyncSession):
    """Successful mining returns a positive amount and increases bio_coins."""
    await create_player(session, tg_id=2001, username="miner1")

    # New formula: base_reward = 50 + total_level * 10. New player has total_level=0 → 50.
    amount, balance_dict, msg = await mine_resources(session, user_id=2001)

    assert amount == 50  # 50 + 0*10 = 50 for a fresh player with no upgrades
    assert "50" in msg
    assert "BioCoins" in msg or "bio" in msg.lower()

    balance = await get_balance(session, user_id=2001)
    assert balance["bio_coins"] == 500 + 50  # 500 starting + 50 mined


async def test_mine_cooldown(session: AsyncSession):
    """Mining while on cooldown returns 0."""
    await create_player(session, tg_id=2002, username="miner2")

    # First mine
    await mine_resources(session, user_id=2002)

    # Second mine right away — should be on cooldown
    amount, _balance, msg = await mine_resources(session, user_id=2002)
    assert amount == 0
    assert "Добыча уже идёт" in msg or "через" in msg


async def test_mine_resources_positive(session: AsyncSession):
    """Mine amount is always positive for any player."""
    await create_player(session, tg_id=2003, username="miner3")
    amount, _balance, _ = await mine_resources(session, user_id=2003)
    # New formula: 50 + total_level*10, minimum 50 for fresh player
    assert amount >= 50


async def test_daily_bonus(session: AsyncSession):
    """First claim of daily bonus returns 200 coins (scalable base for fresh player)."""
    await create_player(session, tg_id=2010, username="daily1")
    amount, _balance, msg = await claim_daily_bonus(session, user_id=2010)

    # New formula: daily_base = 200 + total_level*20. Fresh player: 200 + 0 = 200.
    expected_amount = 200
    assert amount == expected_amount
    assert str(expected_amount) in msg

    balance = await get_balance(session, user_id=2010)
    assert balance["bio_coins"] == 500 + expected_amount  # 500 starting + 200 daily


async def test_daily_bonus_cooldown(session: AsyncSession):
    """Claiming daily bonus twice in a row returns 0 on the second call."""
    await create_player(session, tg_id=2011, username="daily2")
    await claim_daily_bonus(session, user_id=2011)
    amount, _balance, msg = await claim_daily_bonus(session, user_id=2011)

    assert amount == 0
    assert "уже получен" in msg or "через" in msg


async def test_daily_streak(session: AsyncSession):
    """Streak of 2 days gives +15% bonus on the second claim."""
    await create_player(session, tg_id=2012, username="streak1")

    # Simulate first claim 25 hours ago by inserting a backdated transaction
    now_utc = datetime.now(UTC).replace(tzinfo=None)
    old_tx = ResourceTransaction(
        user_id=2012,
        amount=200,
        currency=Currency.BIO_COINS,
        reason=TransactionReason.DAILY_BONUS,
        created_at=now_utc - timedelta(hours=25),
    )
    session.add(old_tx)
    await session.flush()

    amount, _balance, msg = await claim_daily_bonus(session, user_id=2012)

    # Streak 2 → multiplier = 1 + 0.15*(2-1) = 1.15. Fresh player daily_base = 200.
    expected = int(200 * (1.0 + DAILY_STREAK_BONUS * 1))
    assert amount == expected
    assert "стрик" in msg


async def test_get_balance(session: AsyncSession):
    """get_balance returns correct bio_coins and premium_coins."""
    await create_player(session, tg_id=2020, username="balance1")

    balance = await get_balance(session, user_id=2020)
    assert balance == {"bio_coins": 500, "premium_coins": 0}  # new players start with 500


async def test_get_balance_unknown_user(session: AsyncSession):
    """get_balance returns empty dict for an unknown user."""
    balance = await get_balance(session, user_id=999001)
    assert balance == {}
