"""
Unit tests for the multi-tier status system in bot/services/premium.py
"""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.user import User
from bot.services.player import create_player
from bot.services.premium import (
    STATUS_CONFIG,
    UserStatus,
    buy_status,
    get_user_status,
    is_premium,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _naive_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _set_premium_coins(session: AsyncSession, tg_id: int, amount: int) -> None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = result.scalar_one()
    user.premium_coins = amount
    await session.flush()


# ---------------------------------------------------------------------------
# test_get_user_status_free
# ---------------------------------------------------------------------------


async def test_get_user_status_free(session: AsyncSession):
    """A brand-new player has FREE status."""
    await create_player(session, tg_id=6001, username="status_free")

    status = await get_user_status(session, user_id=6001)

    assert status == UserStatus.FREE


# ---------------------------------------------------------------------------
# test_buy_status_bio_plus
# ---------------------------------------------------------------------------


async def test_buy_status_bio_plus(session: AsyncSession):
    """Buying BIO_PLUS succeeds when the user has enough premium coins."""
    cost = STATUS_CONFIG[UserStatus.BIO_PLUS]["price"]
    await create_player(session, tg_id=6010, username="buy_plus")
    await _set_premium_coins(session, 6010, cost)

    success, msg = await buy_status(session, user_id=6010, target=UserStatus.BIO_PLUS)

    assert success is True
    assert "активирована" in msg

    status = await get_user_status(session, user_id=6010)
    assert status == UserStatus.BIO_PLUS

    result = await session.execute(select(User).where(User.tg_id == 6010))
    user = result.scalar_one()
    assert user.premium_coins == 0


# ---------------------------------------------------------------------------
# test_buy_status_bio_pro
# ---------------------------------------------------------------------------


async def test_buy_status_bio_pro(session: AsyncSession):
    """Buying BIO_PRO succeeds when the user has enough premium coins."""
    cost = STATUS_CONFIG[UserStatus.BIO_PRO]["price"]
    await create_player(session, tg_id=6020, username="buy_pro")
    await _set_premium_coins(session, 6020, cost)

    success, msg = await buy_status(session, user_id=6020, target=UserStatus.BIO_PRO)

    assert success is True
    assert "активирована" in msg

    status = await get_user_status(session, user_id=6020)
    assert status == UserStatus.BIO_PRO

    result = await session.execute(select(User).where(User.tg_id == 6020))
    user = result.scalar_one()
    assert user.premium_coins == 0


# ---------------------------------------------------------------------------
# test_buy_status_not_enough_coins
# ---------------------------------------------------------------------------


async def test_buy_status_not_enough_coins(session: AsyncSession):
    """Buying a status fails when the user has fewer coins than the price."""
    cost = STATUS_CONFIG[UserStatus.BIO_PRO]["price"]
    await create_player(session, tg_id=6030, username="poor_status")
    await _set_premium_coins(session, 6030, cost - 1)

    success, msg = await buy_status(session, user_id=6030, target=UserStatus.BIO_PRO)

    assert success is False
    assert "Недостаточно" in msg

    status = await get_user_status(session, user_id=6030)
    assert status == UserStatus.FREE


# ---------------------------------------------------------------------------
# test_status_perks_differ
# ---------------------------------------------------------------------------


async def test_status_perks_differ(session: AsyncSession):
    """BIO_PLUS and BIO_PRO have different mining_cooldown values."""
    plus_cooldown = STATUS_CONFIG[UserStatus.BIO_PLUS]["mining_cooldown"]
    pro_cooldown = STATUS_CONFIG[UserStatus.BIO_PRO]["mining_cooldown"]

    assert plus_cooldown != pro_cooldown, (
        "BIO_PLUS and BIO_PRO should have different mining cooldowns"
    )

    # Also verify that higher status has equal or better cooldown
    assert pro_cooldown <= plus_cooldown, (
        "BIO_PRO mining cooldown should be <= BIO_PLUS (lower is better)"
    )


# ---------------------------------------------------------------------------
# test_buy_legend_forbidden
# ---------------------------------------------------------------------------


async def test_buy_legend_forbidden(session: AsyncSession):
    """BIO_LEGEND cannot be purchased directly."""
    await create_player(session, tg_id=6040, username="legend_try")
    # Give plenty of coins so the only reason for failure is the restriction
    await _set_premium_coins(session, 6040, 99999)

    success, msg = await buy_status(session, user_id=6040, target=UserStatus.BIO_LEGEND)

    assert success is False
    assert "нельзя" in msg.lower()
