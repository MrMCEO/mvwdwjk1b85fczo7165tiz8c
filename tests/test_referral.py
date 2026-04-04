"""
Unit tests for bot/services/referral.py
"""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.referral import Referral, ReferralReward
from bot.models.resource import Currency, ResourceTransaction, TransactionReason
from bot.models.user import User
from bot.services.player import create_player
from bot.services.referral import (
    QUALIFICATION_UPGRADES,
    BOT_USERNAME,
    check_qualification,
    claim_reward,
    get_active_referral_count,
    get_referral_link,
    register_referral,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _naive_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _add_upgrade_transactions(
    session: AsyncSession, user_id: int, count: int
) -> None:
    """Insert *count* UPGRADE debit transactions for *user_id*."""
    for _ in range(count):
        tx = ResourceTransaction(
            user_id=user_id,
            amount=-50,
            currency=Currency.BIO_COINS,
            reason=TransactionReason.UPGRADE,
        )
        session.add(tx)
    await session.flush()


async def _make_qualified_referral(
    session: AsyncSession,
    referrer_id: int,
    referred_id: int,
    referred_username: str,
) -> None:
    """Create a referred player with enough upgrades to be qualified."""
    await create_player(session, tg_id=referred_id, username=referred_username)
    await register_referral(session, referrer_id=referrer_id, referred_id=referred_id)
    await _add_upgrade_transactions(session, referred_id, QUALIFICATION_UPGRADES)
    await check_qualification(session, referred_id)


# ---------------------------------------------------------------------------
# test_register_referral
# ---------------------------------------------------------------------------


async def test_register_referral(session: AsyncSession):
    """Successfully registers a referral between two players."""
    await create_player(session, tg_id=7001, username="referrer1")
    await create_player(session, tg_id=7002, username="referred1")

    result = await register_referral(session, referrer_id=7001, referred_id=7002)

    assert result is True

    row = await session.execute(
        select(Referral).where(Referral.referred_id == 7002)
    )
    referral = row.scalar_one_or_none()
    assert referral is not None
    assert referral.referrer_id == 7001
    assert referral.is_qualified is False


# ---------------------------------------------------------------------------
# test_get_referral_link
# ---------------------------------------------------------------------------


async def test_get_referral_link(session: AsyncSession):
    """get_referral_link returns the correct deep-link URL for the user."""
    link = await get_referral_link(user_id=12345)

    assert BOT_USERNAME in link
    assert "ref_12345" in link
    assert link.startswith("https://t.me/")


# ---------------------------------------------------------------------------
# test_check_qualification
# ---------------------------------------------------------------------------


async def test_check_qualification(session: AsyncSession):
    """Referral is marked qualified when referred user reaches QUALIFICATION_UPGRADES."""
    await create_player(session, tg_id=7010, username="ref_qreferrer")
    await create_player(session, tg_id=7011, username="ref_qreferred")

    await register_referral(session, referrer_id=7010, referred_id=7011)

    # Not yet qualified
    not_yet = await check_qualification(session, referred_id=7011)
    assert not_yet is False

    # Add just enough upgrades
    await _add_upgrade_transactions(session, 7011, QUALIFICATION_UPGRADES)

    qualified = await check_qualification(session, referred_id=7011)
    assert qualified is True

    row = await session.execute(
        select(Referral).where(Referral.referred_id == 7011)
    )
    referral = row.scalar_one()
    assert referral.is_qualified is True


# ---------------------------------------------------------------------------
# test_claim_reward
# ---------------------------------------------------------------------------


async def test_claim_reward(session: AsyncSession):
    """Claiming a reward credits bio_coins and premium_coins to the referrer."""
    await create_player(session, tg_id=7020, username="reward_referrer")

    # Create 1 qualified active referral (level 1 requires 1)
    await _make_qualified_referral(
        session, referrer_id=7020, referred_id=7021, referred_username="rw_ref1"
    )

    success, msg = await claim_reward(session, user_id=7020, level=1)

    assert success is True
    assert "1" in msg  # level 1 mentioned

    result = await session.execute(select(User).where(User.tg_id == 7020))
    user = result.scalar_one()
    # Level 1 reward: 100 bio, 0 premium
    assert user.bio_coins == 100
    assert user.premium_coins == 0


# ---------------------------------------------------------------------------
# test_claim_reward_twice
# ---------------------------------------------------------------------------


async def test_claim_reward_twice(session: AsyncSession):
    """Claiming the same reward level twice fails the second time."""
    await create_player(session, tg_id=7030, username="twice_referrer")

    await _make_qualified_referral(
        session, referrer_id=7030, referred_id=7031, referred_username="tw_ref1"
    )

    first_ok, _ = await claim_reward(session, user_id=7030, level=1)
    assert first_ok is True

    second_ok, msg = await claim_reward(session, user_id=7030, level=1)
    assert second_ok is False
    assert "уже получена" in msg


# ---------------------------------------------------------------------------
# test_active_count
# ---------------------------------------------------------------------------


async def test_active_count(session: AsyncSession):
    """get_active_referral_count returns the correct number of active qualified referrals."""
    await create_player(session, tg_id=7040, username="ac_referrer")

    # Create 2 qualified referrals; they should be active (last_active = now)
    await _make_qualified_referral(
        session, referrer_id=7040, referred_id=7041, referred_username="ac_ref1"
    )
    await _make_qualified_referral(
        session, referrer_id=7040, referred_id=7042, referred_username="ac_ref2"
    )

    count = await get_active_referral_count(session, user_id=7040)
    assert count == 2
