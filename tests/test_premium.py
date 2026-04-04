"""
Unit tests for bot/services/premium.py
"""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.user import User
from bot.services.player import create_player
from bot.services.premium import (
    PREMIUM_COST,
    PREMIUM_DURATION_DAYS,
    buy_premium,
    get_attack_limits,
    get_mining_cooldown,
    get_mining_multiplier,
    get_virus_name_limit,
    is_premium,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _set_premium_coins(session: AsyncSession, tg_id: int, amount: int) -> None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = result.scalar_one()
    user.premium_coins = amount
    await session.flush()


async def _set_premium_until(
    session: AsyncSession, tg_id: int, until: datetime | None
) -> None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = result.scalar_one()
    user.premium_until = until
    await session.flush()


def _naive_utc() -> datetime:
    """Return current naive UTC datetime (matches the service's _now_utc())."""
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# is_premium
# ---------------------------------------------------------------------------


async def test_is_premium_no_subscription(session: AsyncSession):
    """User with no premium_until set is not premium."""
    await create_player(session, tg_id=9001, username="no_sub")

    result = await is_premium(session, user_id=9001)
    assert result is False


async def test_is_premium_active(session: AsyncSession):
    """User with premium_until in the future is premium."""
    await create_player(session, tg_id=9002, username="active_sub")
    future = _naive_utc() + timedelta(days=15)
    await _set_premium_until(session, 9002, future)

    result = await is_premium(session, user_id=9002)
    assert result is True


async def test_is_premium_expired(session: AsyncSession):
    """User whose premium_until is in the past is not premium."""
    await create_player(session, tg_id=9003, username="expired_sub")
    past = _naive_utc() - timedelta(days=1)
    await _set_premium_until(session, 9003, past)

    result = await is_premium(session, user_id=9003)
    assert result is False


# ---------------------------------------------------------------------------
# buy_premium
# ---------------------------------------------------------------------------


async def test_buy_premium(session: AsyncSession):
    """Buying premium with enough coins activates subscription and deducts coins."""
    await create_player(session, tg_id=9010, username="buyer1")
    await _set_premium_coins(session, 9010, PREMIUM_COST)

    success, msg = await buy_premium(session, user_id=9010)

    assert success is True
    assert "активирована" in msg

    # Coins were deducted
    result = await session.execute(select(User).where(User.tg_id == 9010))
    user = result.scalar_one()
    assert user.premium_coins == 0

    # premium_until is roughly now + 30 days
    assert user.premium_until is not None
    expected_min = _naive_utc() + timedelta(days=PREMIUM_DURATION_DAYS - 1)
    expected_max = _naive_utc() + timedelta(days=PREMIUM_DURATION_DAYS + 1)
    assert expected_min <= user.premium_until <= expected_max


async def test_buy_premium_not_enough_coins(session: AsyncSession):
    """Buying premium fails when the user has fewer coins than PREMIUM_COST."""
    await create_player(session, tg_id=9011, username="broke_buyer")
    await _set_premium_coins(session, 9011, PREMIUM_COST - 1)

    success, msg = await buy_premium(session, user_id=9011)

    assert success is False
    assert "Недостаточно" in msg
    assert str(PREMIUM_COST) in msg


async def test_buy_premium_extend(session: AsyncSession):
    """Buying premium while already subscribed extends from the current expiry."""
    await create_player(session, tg_id=9012, username="extender")
    await _set_premium_coins(session, 9012, PREMIUM_COST * 2)

    # Activate subscription first
    await buy_premium(session, user_id=9012)

    result = await session.execute(select(User).where(User.tg_id == 9012))
    user = result.scalar_one()
    first_until = user.premium_until
    assert first_until is not None

    # Extend it
    success, msg = await buy_premium(session, user_id=9012)

    assert success is True
    assert "продлена" in msg

    result2 = await session.execute(select(User).where(User.tg_id == 9012))
    user2 = result2.scalar_one()
    # New expiry should be first_until + PREMIUM_DURATION_DAYS (not from now)
    expected = first_until + timedelta(days=PREMIUM_DURATION_DAYS)
    # Allow ±1 second for timing
    assert abs((user2.premium_until - expected).total_seconds()) < 2


# ---------------------------------------------------------------------------
# Perk getters — mining cooldown
# ---------------------------------------------------------------------------


async def test_get_mining_cooldown_premium(session: AsyncSession):
    """Premium user gets a 45-minute mining cooldown."""
    await create_player(session, tg_id=9020, username="miner_prem")
    await _set_premium_until(session, 9020, _naive_utc() + timedelta(days=10))

    cooldown = await get_mining_cooldown(session, user_id=9020)
    assert cooldown == timedelta(minutes=45)


async def test_get_mining_cooldown_regular(session: AsyncSession):
    """Regular user gets a 60-minute mining cooldown."""
    await create_player(session, tg_id=9021, username="miner_reg")

    cooldown = await get_mining_cooldown(session, user_id=9021)
    assert cooldown == timedelta(minutes=60)


# ---------------------------------------------------------------------------
# Perk getters — attack limits
# ---------------------------------------------------------------------------


async def test_get_attack_limits_premium(session: AsyncSession):
    """Premium user gets (4, 6) attack limits."""
    await create_player(session, tg_id=9030, username="attacker_prem")
    await _set_premium_until(session, 9030, _naive_utc() + timedelta(days=10))

    limits = await get_attack_limits(session, user_id=9030)
    assert limits == (4, 6)


async def test_get_attack_limits_regular(session: AsyncSession):
    """Regular user gets (3, 5) attack limits."""
    await create_player(session, tg_id=9031, username="attacker_reg")

    limits = await get_attack_limits(session, user_id=9031)
    assert limits == (3, 5)


# ---------------------------------------------------------------------------
# Perk getters — mining multiplier
# ---------------------------------------------------------------------------


async def test_get_mining_multiplier_premium(session: AsyncSession):
    """Premium user gets a 1.25 mining multiplier."""
    await create_player(session, tg_id=9040, username="mult_prem")
    await _set_premium_until(session, 9040, _naive_utc() + timedelta(days=10))

    multiplier = await get_mining_multiplier(session, user_id=9040)
    assert multiplier == pytest.approx(1.25)


async def test_get_mining_multiplier_regular(session: AsyncSession):
    """Regular user gets a 1.0 mining multiplier."""
    await create_player(session, tg_id=9041, username="mult_reg")

    multiplier = await get_mining_multiplier(session, user_id=9041)
    assert multiplier == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Perk getters — virus name limit
# ---------------------------------------------------------------------------


async def test_virus_name_limit_premium(session: AsyncSession):
    """Premium user can have a virus name up to 30 characters."""
    await create_player(session, tg_id=9050, username="name_prem")
    await _set_premium_until(session, 9050, _naive_utc() + timedelta(days=10))

    limit = await get_virus_name_limit(session, user_id=9050)
    assert limit == 30


async def test_virus_name_limit_regular(session: AsyncSession):
    """Regular user virus name is capped at 20 characters."""
    await create_player(session, tg_id=9051, username="name_reg")

    limit = await get_virus_name_limit(session, user_id=9051)
    assert limit == 20
