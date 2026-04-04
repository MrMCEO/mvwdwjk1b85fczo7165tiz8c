"""
Unit tests for bot/services/donation.py
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.user import User
from bot.services.donation import EXCHANGE_RATE, add_premium_coins, convert_premium_to_bio
from bot.services.player import create_player


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _set_premium(session: AsyncSession, tg_id: int, amount: int) -> None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = result.scalar_one()
    user.premium_coins = amount
    await session.flush()


async def _get_user(session: AsyncSession, tg_id: int) -> User:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    return result.scalar_one()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_convert_premium_to_bio(session: AsyncSession):
    """Converting premium coins produces the correct number of bio_coins."""
    await create_player(session, tg_id=6001, username="donor1")
    await _set_premium(session, 6001, 10)

    success, msg = await convert_premium_to_bio(session, user_id=6001, amount=5)

    assert success is True
    assert str(5 * EXCHANGE_RATE) in msg

    user = await _get_user(session, 6001)
    assert user.premium_coins == 5
    assert user.bio_coins == 5 * EXCHANGE_RATE


async def test_convert_not_enough_premium(session: AsyncSession):
    """Conversion fails if player doesn't have enough premium_coins."""
    await create_player(session, tg_id=6002, username="donor2")
    # No premium coins by default

    success, msg = await convert_premium_to_bio(session, user_id=6002, amount=1)

    assert success is False
    assert "Недостаточно" in msg


async def test_convert_zero_amount(session: AsyncSession):
    """Conversion with amount=0 fails immediately."""
    await create_player(session, tg_id=6003, username="donor3")
    await _set_premium(session, 6003, 10)

    success, msg = await convert_premium_to_bio(session, user_id=6003, amount=0)
    assert success is False


async def test_convert_negative_amount(session: AsyncSession):
    """Conversion with negative amount fails immediately."""
    await create_player(session, tg_id=6004, username="donor4")
    await _set_premium(session, 6004, 10)

    success, msg = await convert_premium_to_bio(session, user_id=6004, amount=-5)
    assert success is False


async def test_add_premium_coins(session: AsyncSession):
    """add_premium_coins increases premium_coins correctly."""
    await create_player(session, tg_id=6010, username="premium1")

    await add_premium_coins(session, user_id=6010, amount=20)

    user = await _get_user(session, 6010)
    assert user.premium_coins == 20


async def test_add_premium_coins_accumulates(session: AsyncSession):
    """Multiple add_premium_coins calls accumulate correctly."""
    await create_player(session, tg_id=6011, username="premium2")

    await add_premium_coins(session, user_id=6011, amount=10)
    await add_premium_coins(session, user_id=6011, amount=5)

    user = await _get_user(session, 6011)
    assert user.premium_coins == 15


async def test_add_premium_coins_zero_raises(session: AsyncSession):
    """add_premium_coins raises ValueError for amount=0."""
    await create_player(session, tg_id=6012, username="premium3")

    with pytest.raises(ValueError):
        await add_premium_coins(session, user_id=6012, amount=0)


async def test_add_premium_coins_unknown_user_raises(session: AsyncSession):
    """add_premium_coins raises LookupError for unknown user."""
    with pytest.raises(LookupError):
        await add_premium_coins(session, user_id=999004, amount=10)


async def test_convert_full_balance(session: AsyncSession):
    """Player can convert their entire premium balance."""
    await create_player(session, tg_id=6020, username="all_in")
    await _set_premium(session, 6020, 7)

    success, msg = await convert_premium_to_bio(session, user_id=6020, amount=7)

    assert success is True
    user = await _get_user(session, 6020)
    assert user.premium_coins == 0
    assert user.bio_coins == 7 * EXCHANGE_RATE
