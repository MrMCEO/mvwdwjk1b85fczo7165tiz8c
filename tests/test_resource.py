"""
Unit tests for bot/services/resource.py
"""
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.resource import (
    Currency,
    ResourceTransaction,
    TransactionReason,
)
from bot.services.player import create_player
from bot.services.resource import (
    DAILY_BASE,
    DAILY_STREAK_BONUS,
    MINING_MAX,
    MINING_MIN,
    claim_daily_bonus,
    get_balance,
    mine_resources,
)


async def test_mine_resources(session: AsyncSession):
    """Successful mining returns a positive amount and increases bio_coins."""
    await create_player(session, tg_id=2001, username="miner1")

    with patch("bot.services.resource.random.randint", return_value=30):
        amount, msg = await mine_resources(session, user_id=2001)

    assert amount == 30
    assert "30" in msg
    assert "bio_coins" in msg

    balance = await get_balance(session, user_id=2001)
    assert balance["bio_coins"] == 30


async def test_mine_cooldown(session: AsyncSession):
    """Mining while on cooldown returns 0."""
    await create_player(session, tg_id=2002, username="miner2")

    # First mine
    with patch("bot.services.resource.random.randint", return_value=10):
        await mine_resources(session, user_id=2002)

    # Second mine right away — should be on cooldown
    amount, msg = await mine_resources(session, user_id=2002)
    assert amount == 0
    assert "Добыча уже идёт" in msg or "через" in msg


async def test_mine_resources_bounds(session: AsyncSession):
    """Mine amount respects MINING_MIN / MINING_MAX boundaries (via actual random)."""
    await create_player(session, tg_id=2003, username="miner3")
    amount, _ = await mine_resources(session, user_id=2003)
    # real random — just assert range
    assert MINING_MIN <= amount <= MINING_MAX


async def test_daily_bonus(session: AsyncSession):
    """First claim of daily bonus returns DAILY_BASE coins."""
    await create_player(session, tg_id=2010, username="daily1")
    amount, msg = await claim_daily_bonus(session, user_id=2010)

    assert amount == DAILY_BASE
    assert str(DAILY_BASE) in msg

    balance = await get_balance(session, user_id=2010)
    assert balance["bio_coins"] == DAILY_BASE


async def test_daily_bonus_cooldown(session: AsyncSession):
    """Claiming daily bonus twice in a row returns 0 on the second call."""
    await create_player(session, tg_id=2011, username="daily2")
    await claim_daily_bonus(session, user_id=2011)
    amount, msg = await claim_daily_bonus(session, user_id=2011)

    assert amount == 0
    assert "уже получен" in msg or "через" in msg


async def test_daily_streak(session: AsyncSession):
    """Streak of 2 days gives +10% bonus on the second claim."""
    await create_player(session, tg_id=2012, username="streak1")

    # Simulate first claim 25 hours ago by inserting a backdated transaction
    now_utc = datetime.now(UTC).replace(tzinfo=None)
    old_tx = ResourceTransaction(
        user_id=2012,
        amount=DAILY_BASE,
        currency=Currency.BIO_COINS,
        reason=TransactionReason.DAILY_BONUS,
        created_at=now_utc - timedelta(hours=25),
    )
    session.add(old_tx)
    await session.flush()

    # Set bio_coins to DAILY_BASE so total is meaningful
    from sqlalchemy import select
    from bot.models.user import User
    result = await session.execute(select(User).where(User.tg_id == 2012))
    user = result.scalar_one()
    user.bio_coins = DAILY_BASE
    await session.flush()

    amount, msg = await claim_daily_bonus(session, user_id=2012)

    # Streak 2 → multiplier = 1 + 0.10*(2-1) = 1.10
    expected = int(DAILY_BASE * (1.0 + DAILY_STREAK_BONUS * 1))
    assert amount == expected
    assert "стрик" in msg


async def test_get_balance(session: AsyncSession):
    """get_balance returns correct bio_coins and premium_coins."""
    await create_player(session, tg_id=2020, username="balance1")

    balance = await get_balance(session, user_id=2020)
    assert balance == {"bio_coins": 0, "premium_coins": 0}


async def test_get_balance_unknown_user(session: AsyncSession):
    """get_balance returns empty dict for an unknown user."""
    balance = await get_balance(session, user_id=999001)
    assert balance == {}
