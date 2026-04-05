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
    REPEATABLE_BASE_THRESHOLD,
    REPEATABLE_BIO,
    REPEATABLE_STEP,
    BOT_USERNAME,
    _available_repeatable_claims,
    check_qualification,
    claim_repeatable_reward,
    claim_reward,
    get_active_referral_count,
    get_referral_link,
    get_referral_stats,
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


async def _make_n_qualified_referrals(
    session: AsyncSession,
    referrer_id: int,
    n: int,
    id_offset: int = 9000,
) -> None:
    """Create *n* qualified active referrals for *referrer_id*."""
    for i in range(n):
        uid = id_offset + i
        await _make_qualified_referral(
            session,
            referrer_id=referrer_id,
            referred_id=uid,
            referred_username=f"ref_{uid}",
        )


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


# ---------------------------------------------------------------------------
# test_available_repeatable_claims — pure function
# ---------------------------------------------------------------------------


def test_available_repeatable_claims_below_base():
    """Below base threshold: no repeatable claims available."""
    assert _available_repeatable_claims(0, 0) == 0
    assert _available_repeatable_claims(49, 0) == 0
    assert _available_repeatable_claims(50, 0) == 0


def test_available_repeatable_claims_first_step():
    """Exactly REPEATABLE_STEP above base: 1 claim available."""
    assert _available_repeatable_claims(REPEATABLE_BASE_THRESHOLD + REPEATABLE_STEP, 0) == 1


def test_available_repeatable_claims_multiple_steps():
    """Multiple steps above base."""
    assert _available_repeatable_claims(REPEATABLE_BASE_THRESHOLD + 3 * REPEATABLE_STEP, 0) == 3


def test_available_repeatable_claims_already_claimed():
    """Already claimed some: subtract from earned."""
    active = REPEATABLE_BASE_THRESHOLD + 3 * REPEATABLE_STEP
    assert _available_repeatable_claims(active, 1) == 2
    assert _available_repeatable_claims(active, 3) == 0
    assert _available_repeatable_claims(active, 5) == 0  # can't go negative


def test_available_repeatable_claims_partial_step():
    """Partial step above last earned: no new claim yet."""
    active = REPEATABLE_BASE_THRESHOLD + REPEATABLE_STEP + 5  # halfway through 2nd step
    assert _available_repeatable_claims(active, 1) == 0


# ---------------------------------------------------------------------------
# test_claim_repeatable_reward — not enough referrals
# ---------------------------------------------------------------------------


async def test_claim_repeatable_reward_not_enough(session: AsyncSession):
    """Claiming repeatable reward fails when below base threshold."""
    await create_player(session, tg_id=8000, username="rep_fail_referrer")

    # Only 5 referrals — not enough
    await _make_n_qualified_referrals(session, referrer_id=8000, n=5, id_offset=8001)

    success, msg = await claim_repeatable_reward(session, user_id=8000)
    assert success is False
    assert "Недостаточно" in msg


# ---------------------------------------------------------------------------
# test_claim_repeatable_reward — first claim
# ---------------------------------------------------------------------------


async def test_claim_repeatable_reward_first_claim(session: AsyncSession):
    """Claiming repeatable reward succeeds after base_threshold + step referrals."""
    await create_player(session, tg_id=8100, username="rep_ok_referrer")

    n = REPEATABLE_BASE_THRESHOLD + REPEATABLE_STEP  # 60
    await _make_n_qualified_referrals(session, referrer_id=8100, n=n, id_offset=8101)

    success, msg = await claim_repeatable_reward(session, user_id=8100)
    assert success is True
    assert str(REPEATABLE_BIO) in msg

    # User got the coins
    result = await session.execute(select(User).where(User.tg_id == 8100))
    user = result.scalar_one()
    assert user.bio_coins == REPEATABLE_BIO
    assert user.repeatable_referral_claims == 1


# ---------------------------------------------------------------------------
# test_claim_repeatable_reward — cannot claim twice without more referrals
# ---------------------------------------------------------------------------


async def test_claim_repeatable_reward_no_double_claim(session: AsyncSession):
    """After claiming once, must get REPEATABLE_STEP more referrals for next claim."""
    await create_player(session, tg_id=8200, username="rep_double_referrer")

    n = REPEATABLE_BASE_THRESHOLD + REPEATABLE_STEP  # exactly 60
    await _make_n_qualified_referrals(session, referrer_id=8200, n=n, id_offset=8201)

    first_ok, _ = await claim_repeatable_reward(session, user_id=8200)
    assert first_ok is True

    # No more referrals added — second claim should fail
    second_ok, msg = await claim_repeatable_reward(session, user_id=8200)
    assert second_ok is False
    assert "Недостаточно" in msg


# ---------------------------------------------------------------------------
# test_claim_repeatable_reward — multiple sequential claims
# ---------------------------------------------------------------------------


async def test_claim_repeatable_reward_multiple_claims(session: AsyncSession):
    """Can claim multiple times as referral count grows in steps."""
    await create_player(session, tg_id=8300, username="rep_multi_referrer")

    # Start with base + 2 steps = 70 referrals → 2 claims available
    n = REPEATABLE_BASE_THRESHOLD + 2 * REPEATABLE_STEP
    await _make_n_qualified_referrals(session, referrer_id=8300, n=n, id_offset=8301)

    ok1, _ = await claim_repeatable_reward(session, user_id=8300)
    assert ok1 is True

    ok2, _ = await claim_repeatable_reward(session, user_id=8300)
    assert ok2 is True

    ok3, _ = await claim_repeatable_reward(session, user_id=8300)
    assert ok3 is False  # only 2 steps earned

    result = await session.execute(select(User).where(User.tg_id == 8300))
    user = result.scalar_one()
    assert user.bio_coins == REPEATABLE_BIO * 2
    assert user.repeatable_referral_claims == 2


# ---------------------------------------------------------------------------
# test_get_referral_stats — repeatable fields present
# ---------------------------------------------------------------------------


async def test_get_referral_stats_repeatable_fields(session: AsyncSession):
    """get_referral_stats includes repeatable reward fields."""
    await create_player(session, tg_id=8400, username="stats_rep_referrer")

    stats = await get_referral_stats(session, user_id=8400)

    assert "repeatable_available" in stats
    assert "repeatable_claimed" in stats
    assert "repeatable_bio" in stats
    assert "repeatable_step" in stats
    assert "repeatable_base" in stats

    assert stats["repeatable_available"] == 0
    assert stats["repeatable_claimed"] == 0
    assert stats["repeatable_bio"] == REPEATABLE_BIO
    assert stats["repeatable_step"] == REPEATABLE_STEP
    assert stats["repeatable_base"] == REPEATABLE_BASE_THRESHOLD


async def test_get_referral_stats_repeatable_available(session: AsyncSession):
    """get_referral_stats correctly reports available repeatable claims."""
    await create_player(session, tg_id=8500, username="stats_rep2_referrer")

    n = REPEATABLE_BASE_THRESHOLD + REPEATABLE_STEP
    await _make_n_qualified_referrals(session, referrer_id=8500, n=n, id_offset=8501)

    stats = await get_referral_stats(session, user_id=8500)
    assert stats["repeatable_available"] == 1
