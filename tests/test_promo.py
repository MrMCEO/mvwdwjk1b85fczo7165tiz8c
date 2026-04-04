"""
Unit tests for bot/services/promo.py
"""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.player import create_player
from bot.services.promo import activate_promo, create_promo


async def test_create_promo(session: AsyncSession):
    """Admin can create a promo code successfully."""
    ok, msg = await create_promo(
        session,
        code="TESTCODE1",
        bio_coins=500,
        premium_coins=0,
        max_activations=10,
        created_by=1,
    )
    assert ok is True
    assert "TESTCODE1" in msg


async def test_create_promo_duplicate(session: AsyncSession):
    """Creating a duplicate promo code fails."""
    await create_promo(
        session,
        code="DUPL1",
        bio_coins=100,
        premium_coins=0,
        max_activations=5,
        created_by=1,
    )
    ok, msg = await create_promo(
        session,
        code="DUPL1",
        bio_coins=200,
        premium_coins=0,
        max_activations=5,
        created_by=1,
    )
    assert ok is False
    assert "уже существует" in msg


async def test_activate_promo(session: AsyncSession):
    """A player can successfully activate a valid promo code."""
    await create_player(session, tg_id=9001, username="promouser1")

    await create_promo(
        session,
        code="WELCOME1",
        bio_coins=200,
        premium_coins=0,
        max_activations=10,
        created_by=1,
    )

    ok, msg = await activate_promo(session, user_id=9001, code="welcome1")
    assert ok is True
    assert "200" in msg
    assert "WELCOME1" in msg


async def test_activate_promo_case_insensitive(session: AsyncSession):
    """Promo activation is case-insensitive."""
    await create_player(session, tg_id=9002, username="promouser2")

    await create_promo(
        session,
        code="UPPER2",
        bio_coins=100,
        premium_coins=0,
        max_activations=5,
        created_by=1,
    )

    ok, msg = await activate_promo(session, user_id=9002, code="upper2")
    assert ok is True


async def test_activate_promo_twice(session: AsyncSession):
    """Activating the same promo code twice fails on the second attempt."""
    await create_player(session, tg_id=9003, username="promouser3")

    await create_promo(
        session,
        code="ONCE3",
        bio_coins=100,
        premium_coins=0,
        max_activations=10,
        created_by=1,
    )

    ok1, _ = await activate_promo(session, user_id=9003, code="ONCE3")
    assert ok1 is True

    ok2, msg = await activate_promo(session, user_id=9003, code="ONCE3")
    assert ok2 is False
    assert "уже активировал" in msg


async def test_activate_expired_promo(session: AsyncSession):
    """Activating an expired promo code fails."""
    await create_player(session, tg_id=9004, username="promouser4")

    # Create a promo that expired in the past by using a negative expires_hours
    # We create it manually since create_promo only accepts positive hours
    from bot.models.promo import PromoCode
    now = datetime.now(UTC).replace(tzinfo=None)
    expired_promo = PromoCode(
        code="EXPIRED4",
        bio_coins=100,
        premium_coins=0,
        max_activations=10,
        current_activations=0,
        created_by=1,
        expires_at=now - timedelta(hours=1),
        is_active=True,
    )
    session.add(expired_promo)
    await session.flush()

    ok, msg = await activate_promo(session, user_id=9004, code="EXPIRED4")
    assert ok is False
    assert "истёк" in msg


async def test_activate_promo_limit_exceeded(session: AsyncSession):
    """Activating a promo that reached its max activations fails."""
    await create_player(session, tg_id=9005, username="promouser5")
    await create_player(session, tg_id=9006, username="promouser6")

    await create_promo(
        session,
        code="LIMIT5",
        bio_coins=100,
        premium_coins=0,
        max_activations=1,
        created_by=1,
    )

    # First activation
    ok1, _ = await activate_promo(session, user_id=9005, code="LIMIT5")
    assert ok1 is True

    # Second activation — limit reached
    ok2, msg = await activate_promo(session, user_id=9006, code="LIMIT5")
    assert ok2 is False
    assert "лимит" in msg


async def test_activate_nonexistent_promo(session: AsyncSession):
    """Activating a nonexistent promo code fails."""
    await create_player(session, tg_id=9007, username="promouser7")

    ok, msg = await activate_promo(session, user_id=9007, code="DOESNOTEXIST")
    assert ok is False
    assert "не найден" in msg


async def test_activate_promo_credits_coins(session: AsyncSession):
    """Activating a promo with both bio and premium coins credits both."""
    await create_player(session, tg_id=9010, username="richuser10")

    await create_promo(
        session,
        code="BOTH10",
        bio_coins=300,
        premium_coins=50,
        max_activations=5,
        created_by=1,
    )

    ok, msg = await activate_promo(session, user_id=9010, code="BOTH10")
    assert ok is True

    from sqlalchemy import select
    from bot.models.user import User
    result = await session.execute(select(User).where(User.tg_id == 9010))
    user = result.scalar_one()
    assert user.bio_coins == 300
    assert user.premium_coins == 50
