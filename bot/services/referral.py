"""
Referral program service.

Responsibilities:
  - get_referral_link: generate bot deep-link for a user.
  - register_referral: record a new referral relationship.
  - check_qualification: mark referral as qualified after QUALIFICATION_UPGRADES upgrades.
  - get_active_referral_count: count qualified referrals active within INACTIVITY_DAYS.
  - get_referral_stats: full stats dict for the referral menu.
  - claim_reward: award bio/premium coins (and optionally a status) for a reward level.
  - claim_repeatable_reward: award the infinite repeatable reward (each 10 referrals beyond
    REPEATABLE_BASE_THRESHOLD).
  - deactivate_stale_referrals: called from the tick — marks old referrals inactive.
  - update_referral_activity: call on any user action to keep last_active fresh.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.referral import Referral, ReferralReward
from bot.models.resource import Currency as CurrencyType
from bot.models.resource import ResourceTransaction, TransactionReason
from bot.models.user import User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BOT_USERNAME = "BestBIOwarsrobot"

REFERRAL_REWARDS: list[dict] = [
    {"level": 1,  "required": 1,  "bio": 100,   "premium": 0,   "status": None,        "status_days": 0},
    {"level": 2,  "required": 3,  "bio": 300,   "premium": 0,   "status": None,        "status_days": 0},
    {"level": 3,  "required": 5,  "bio": 500,   "premium": 10,  "status": None,        "status_days": 0},
    {"level": 4,  "required": 10, "bio": 1000,  "premium": 30,  "status": None,        "status_days": 0},
    {"level": 5,  "required": 20, "bio": 2000,  "premium": 50,  "status": "BIO_PLUS",  "status_days": 7},
    {"level": 6,  "required": 35, "bio": 5000,  "premium": 100, "status": "BIO_PRO",   "status_days": 14},
    {"level": 7,  "required": 50, "bio": 10000, "premium": 200, "status": "BIO_LEGEND","status_days": 0},
]

# A referral must do this many upgrades to be considered «qualified»
QUALIFICATION_UPGRADES: int = 5

# Qualified referrals inactive for this many days are excluded from the active count
INACTIVITY_DAYS: int = 7

# ---------------------------------------------------------------------------
# Repeatable (infinite) reward configuration
# ---------------------------------------------------------------------------

# Threshold of referrals for the last regular level (level 7)
REPEATABLE_BASE_THRESHOLD: int = 50

# Every REPEATABLE_STEP active referrals above the base threshold earns one claim
REPEATABLE_STEP: int = 10

# Bio coins awarded per repeatable claim
REPEATABLE_BIO: int = 1000


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _reward_by_level(level: int) -> dict | None:
    for r in REFERRAL_REWARDS:
        if r["level"] == level:
            return r
    return None


def _available_repeatable_claims(active_count: int, already_claimed: int) -> int:
    """
    Calculate how many repeatable reward claims are currently available.

    Formula:
        available = (active_count - REPEATABLE_BASE_THRESHOLD) // REPEATABLE_STEP
                    - already_claimed

    Returns 0 if below base threshold.
    """
    if active_count <= REPEATABLE_BASE_THRESHOLD:
        return 0
    earned = (active_count - REPEATABLE_BASE_THRESHOLD) // REPEATABLE_STEP
    return max(0, earned - already_claimed)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_referral_link(user_id: int) -> str:
    """Return the deep-link referral URL for *user_id*."""
    return f"https://t.me/{BOT_USERNAME}?start=ref_{user_id}"


async def register_referral(
    session: AsyncSession,
    referrer_id: int,
    referred_id: int,
) -> bool:
    """
    Record that *referred_id* was invited by *referrer_id*.

    Returns True if the referral was successfully saved, False if:
      - referrer == referred (self-referral)
      - referred_id already has a referrer
      - referrer_id does not exist
    """
    if referrer_id == referred_id:
        logger.debug("register_referral: self-referral ignored (user=%d)", referrer_id)
        return False

    # Check if referred_id already has a referral row (unique constraint on referred_id)
    existing = await session.execute(
        select(Referral).where(Referral.referred_id == referred_id)
    )
    if existing.scalar_one_or_none() is not None:
        logger.debug(
            "register_referral: referred_id=%d already has a referrer, ignored.", referred_id
        )
        return False

    # Make sure the referrer exists
    referrer = await session.execute(
        select(User).where(User.tg_id == referrer_id)
    )
    if referrer.scalar_one_or_none() is None:
        logger.debug(
            "register_referral: referrer_id=%d does not exist, ignored.", referrer_id
        )
        return False

    ref = Referral(
        referrer_id=referrer_id,
        referred_id=referred_id,
        is_qualified=False,
        last_active=_now_utc(),
    )
    session.add(ref)
    await session.flush()
    logger.info(
        "register_referral: referrer=%d referred=%d saved.", referrer_id, referred_id
    )
    return True


async def check_qualification(session: AsyncSession, referred_id: int) -> bool:
    """
    Check whether *referred_id* has reached QUALIFICATION_UPGRADES total upgrade
    purchases; if so, mark the referral row as qualified.

    Returns True if the referral row was just qualified (transition False → True).
    """
    # Find the referral row for this user (they are the referred side)
    result = await session.execute(
        select(Referral).where(Referral.referred_id == referred_id)
    )
    referral = result.scalar_one_or_none()
    if referral is None or referral.is_qualified:
        # No referral row or already qualified — nothing to do
        return False

    # Count total upgrade transactions for this user
    # Each call to upgrade_virus_branch / upgrade_immunity_branch adds one
    # ResourceTransaction with reason=UPGRADE.
    upgrade_count_result = await session.execute(
        select(func.count()).where(
            and_(
                ResourceTransaction.user_id == referred_id,
                ResourceTransaction.reason == TransactionReason.UPGRADE,
                ResourceTransaction.amount < 0,  # outgoing = real upgrade payment
            )
        )
    )
    upgrade_count: int = upgrade_count_result.scalar_one()

    if upgrade_count >= QUALIFICATION_UPGRADES:
        referral.is_qualified = True
        await session.flush()
        logger.info(
            "check_qualification: referred_id=%d qualified (upgrades=%d).",
            referred_id, upgrade_count,
        )
        return True

    return False


async def get_active_referral_count(session: AsyncSession, user_id: int) -> int:
    """
    Return the number of qualified referrals that have been active within INACTIVITY_DAYS.
    """
    cutoff = _now_utc() - timedelta(days=INACTIVITY_DAYS)
    result = await session.execute(
        select(func.count()).where(
            and_(
                Referral.referrer_id == user_id,
                Referral.is_qualified == True,  # noqa: E712
                Referral.last_active >= cutoff,
            )
        )
    )
    return result.scalar_one()


async def get_referral_stats(session: AsyncSession, user_id: int) -> dict:
    """
    Return full referral stats for *user_id*.

    Keys:
      total_referrals          int   — total rows where referrer_id == user_id
      qualified_count          int   — qualified referrals (regardless of activity)
      active_count             int   — qualified + active within INACTIVITY_DAYS
      current_level            int   — highest level whose required count is met
      rewards                  list  — list of dicts with status per reward level
        Each item: {level, required, bio, premium, status, status_days,
                    is_claimed, is_available}
        is_available = active_count >= required AND NOT is_claimed
      repeatable_available     int   — how many repeatable claims are currently available
      repeatable_claimed       int   — how many times repeatable reward was already claimed
      repeatable_bio           int   — bio per repeatable claim
      repeatable_step          int   — referrals needed per repeatable claim
      repeatable_base          int   — base threshold (last regular level)
    """
    # Total referrals
    total_result = await session.execute(
        select(func.count()).where(Referral.referrer_id == user_id)
    )
    total_referrals: int = total_result.scalar_one()

    # Qualified count (regardless of activity window)
    qualified_result = await session.execute(
        select(func.count()).where(
            and_(
                Referral.referrer_id == user_id,
                Referral.is_qualified == True,  # noqa: E712
            )
        )
    )
    qualified_count: int = qualified_result.scalar_one()

    # Active count (qualified + active within window)
    active_count: int = await get_active_referral_count(session, user_id)

    # Already claimed reward levels
    claimed_result = await session.execute(
        select(ReferralReward.level).where(ReferralReward.user_id == user_id)
    )
    claimed_levels: set[int] = set(claimed_result.scalars().all())

    # Repeatable claims already made (stored on the user row)
    user_result = await session.execute(select(User).where(User.tg_id == user_id))
    user = user_result.scalar_one_or_none()
    repeatable_claimed: int = user.repeatable_referral_claims if user else 0

    # Determine current level (highest fully met reward)
    current_level = 0
    for reward in REFERRAL_REWARDS:
        if active_count >= reward["required"]:
            current_level = reward["level"]

    # Build rewards list
    rewards = []
    for reward in REFERRAL_REWARDS:
        is_claimed = reward["level"] in claimed_levels
        is_available = (
            active_count >= reward["required"] and not is_claimed
        )
        rewards.append(
            {
                **reward,
                "is_claimed": is_claimed,
                "is_available": is_available,
            }
        )

    repeatable_available = _available_repeatable_claims(active_count, repeatable_claimed)

    return {
        "total_referrals": total_referrals,
        "qualified_count": qualified_count,
        "active_count": active_count,
        "current_level": current_level,
        "rewards": rewards,
        "repeatable_available": repeatable_available,
        "repeatable_claimed": repeatable_claimed,
        "repeatable_bio": REPEATABLE_BIO,
        "repeatable_step": REPEATABLE_STEP,
        "repeatable_base": REPEATABLE_BASE_THRESHOLD,
    }


async def claim_reward(
    session: AsyncSession, user_id: int, level: int
) -> tuple[bool, str]:
    """
    Claim the reward for *level*.

    Returns (success, message).
    Failures:
      - level not found in REFERRAL_REWARDS
      - already claimed
      - not enough active referrals
    """
    reward_cfg = _reward_by_level(level)
    if reward_cfg is None:
        return False, f"Уровень {level} не существует."

    # Already claimed?
    existing = await session.execute(
        select(ReferralReward).where(
            and_(
                ReferralReward.user_id == user_id,
                ReferralReward.level == level,
            )
        )
    )
    if existing.scalar_one_or_none() is not None:
        return False, f"Награда уровня {level} уже получена."

    # Enough active referrals?
    active_count = await get_active_referral_count(session, user_id)
    if active_count < reward_cfg["required"]:
        return False, (
            f"Недостаточно активных рефералов. "
            f"Нужно {reward_cfg['required']}, у тебя {active_count}."
        )

    # Fetch user with lock to prevent concurrent races
    user_result = await session.execute(
        select(User).where(User.tg_id == user_id).with_for_update()
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        return False, "Пользователь не найден."

    # Re-check "already claimed" AFTER acquiring the row lock (closes TOCTOU window).
    # The unique constraint on (user_id, level) provides a DB-level safety net too.
    existing_after_lock = await session.execute(
        select(ReferralReward).where(
            and_(
                ReferralReward.user_id == user_id,
                ReferralReward.level == level,
            )
        )
    )
    if existing_after_lock.scalar_one_or_none() is not None:
        return False, f"Награда уровня {level} уже получена."

    # Grant bio coins
    bio = reward_cfg["bio"]
    if bio > 0:
        user.bio_coins += bio
        tx = ResourceTransaction(
            user_id=user_id,
            amount=bio,
            currency=CurrencyType.BIO_COINS,
            reason=TransactionReason.REFERRAL_REWARD,
        )
        session.add(tx)

    # Grant premium coins
    premium = reward_cfg["premium"]
    if premium > 0:
        user.premium_coins += premium
        tx_p = ResourceTransaction(
            user_id=user_id,
            amount=premium,
            currency=CurrencyType.PREMIUM_COINS,
            reason=TransactionReason.REFERRAL_REWARD,
        )
        session.add(tx_p)

    # Record reward as claimed
    rr = ReferralReward(user_id=user_id, level=level)
    session.add(rr)

    await session.flush()

    parts: list[str] = [f"+{bio} 🧫 BioCoins" if bio > 0 else ""]
    if premium > 0:
        parts.append(f"+{premium} 💎")
    reward_str = ", ".join(p for p in parts if p)
    logger.info("claim_reward: user=%d level=%d awarded: %s", user_id, level, reward_str)
    return True, f"🎁 Получена награда уровня {level}! {reward_str}"


async def claim_repeatable_reward(
    session: AsyncSession, user_id: int
) -> tuple[bool, str]:
    """
    Claim one instance of the infinite repeatable reward.

    Every REPEATABLE_STEP active referrals above REPEATABLE_BASE_THRESHOLD
    earns one claim worth REPEATABLE_BIO bio coins.

    Returns (success, message).
    """
    # Fetch user with lock to prevent concurrent double-claims
    user_result = await session.execute(
        select(User).where(User.tg_id == user_id).with_for_update()
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        return False, "Пользователь не найден."

    active_count = await get_active_referral_count(session, user_id)
    available = _available_repeatable_claims(active_count, user.repeatable_referral_claims)

    if available <= 0:
        needed_total = REPEATABLE_BASE_THRESHOLD + (user.repeatable_referral_claims + 1) * REPEATABLE_STEP
        return False, (
            f"Недостаточно активных рефералов для бесконечной награды. "
            f"Нужно {needed_total}, у тебя {active_count}."
        )

    # Award one claim
    user.bio_coins += REPEATABLE_BIO
    user.repeatable_referral_claims += 1

    tx = ResourceTransaction(
        user_id=user_id,
        amount=REPEATABLE_BIO,
        currency=CurrencyType.BIO_COINS,
        reason=TransactionReason.REFERRAL_REWARD,
    )
    session.add(tx)

    await session.flush()

    logger.info(
        "claim_repeatable_reward: user=%d claim_no=%d awarded +%d bio",
        user_id, user.repeatable_referral_claims, REPEATABLE_BIO,
    )
    return True, f"🔄 Бесконечная награда получена! +{REPEATABLE_BIO} 🧫 BioCoins"


async def deactivate_stale_referrals(session: AsyncSession) -> int:
    """
    Deactivate referrals whose last_active is older than INACTIVITY_DAYS.

    Sets is_qualified = False for stale records so they no longer count
    towards the active referral count.

    Returns the number of records deactivated.
    """
    cutoff = _now_utc() - timedelta(days=INACTIVITY_DAYS)
    result = await session.execute(
        select(Referral).where(
            and_(
                Referral.is_qualified == True,  # noqa: E712
                Referral.last_active < cutoff,
            )
        )
    )
    stale = result.scalars().all()
    count = 0
    for ref in stale:
        ref.is_qualified = False
        count += 1

    if count:
        await session.flush()
        logger.info("deactivate_stale_referrals: deactivated %d referral(s).", count)

    return count


async def update_referral_activity(session: AsyncSession, user_id: int) -> None:
    """
    Update last_active for *user_id*'s referral row (they are the referred side).

    Call this on any significant user action (upgrade, attack, mine, etc.)
    Also re-qualify the referral if it was previously deactivated due to inactivity
    and they have enough upgrades to qualify again.
    """
    result = await session.execute(
        select(Referral).where(Referral.referred_id == user_id)
    )
    referral = result.scalar_one_or_none()
    if referral is None:
        return

    referral.last_active = _now_utc()

    # If the referral was deactivated (is_qualified=False) but had previously
    # been qualified, we may need to re-qualify them.
    if not referral.is_qualified:
        upgrade_count_result = await session.execute(
            select(func.count()).where(
                and_(
                    ResourceTransaction.user_id == user_id,
                    ResourceTransaction.reason == TransactionReason.UPGRADE,
                    ResourceTransaction.amount < 0,
                )
            )
        )
        upgrade_count: int = upgrade_count_result.scalar_one()
        if upgrade_count >= QUALIFICATION_UPGRADES:
            referral.is_qualified = True
            logger.info(
                "update_referral_activity: re-qualified referred_id=%d.", user_id
            )

    await session.flush()
