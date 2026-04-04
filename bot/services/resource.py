"""
Resource service — bio_coins mining and daily bonus logic.

TODO: The following fields are needed on the User model (bot/models/user.py):
  - last_mining_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
  - last_daily_at:  Mapped[datetime | None] = mapped_column(DateTime, nullable=True, default=None)
  - daily_streak:   Mapped[int]             = mapped_column(Integer, default=0, server_default="0")

Until those columns exist we derive cooldown state from ResourceTransaction records
(last transaction with the corresponding reason), which is always consistent with the
DB even if the application is restarted.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.resource import (
    Currency as CurrencyType,
)
from bot.models.resource import (
    ResourceTransaction,
    TransactionReason,
)
from bot.models.user import User
from bot.services.premium import get_daily_multiplier, get_mining_cooldown, get_mining_multiplier

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DAILY_COOLDOWN = timedelta(hours=24)

MINING_MIN = 15   # balanced: ~32 avg/hr, 1st upgrade (~80 coins) in ~2.5hrs
MINING_MAX = 50

DAILY_BASE = 100
DAILY_STREAK_BONUS = 0.15   # +15% per consecutive day (was 10%); rewards loyal players more
DAILY_STREAK_MAX = 7        # cap at day 7 → +90 %

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_user(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(
        select(User).where(User.tg_id == user_id).with_for_update()
    )
    return result.scalar_one_or_none()


async def _last_transaction(
    session: AsyncSession,
    user_id: int,
    reason: TransactionReason,
) -> ResourceTransaction | None:
    """Return the most recent ResourceTransaction for *user_id* with given reason."""
    result = await session.execute(
        select(ResourceTransaction)
        .where(
            ResourceTransaction.user_id == user_id,
            ResourceTransaction.reason == reason,
        )
        .order_by(desc(ResourceTransaction.created_at))
        .limit(1)
    )
    return result.scalar_one_or_none()


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)  # store naive UTC in DB


def _seconds_left(since: datetime, cooldown: timedelta) -> int:
    """Return remaining cooldown seconds (0 if already expired)."""
    elapsed = _now_utc() - since
    remaining = cooldown - elapsed
    return max(0, int(remaining.total_seconds()))


def _fmt_cooldown(seconds: int) -> str:
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}ч {m}м"
    if m:
        return f"{m}м {s}с"
    return f"{s}с"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def mine_resources(
    session: AsyncSession, user_id: int
) -> tuple[int, str]:
    """
    Try to mine bio_coins for *user_id*.

    Returns (amount, message):
      - amount == 0  → cooldown still active, message contains time left
      - amount  > 0  → successful mining, message is a success string
    """
    user = await _get_user(session, user_id)
    if user is None:
        return 0, "Пользователь не найден."

    # --- Cooldown check via last MINING transaction ---
    mining_cooldown = await get_mining_cooldown(session, user_id)
    last_tx = await _last_transaction(session, user_id, TransactionReason.MINING)
    if last_tx is not None:
        seconds = _seconds_left(last_tx.created_at, mining_cooldown)
        if seconds > 0:
            return 0, (
                f"Добыча уже идёт. Следующая добыча через {_fmt_cooldown(seconds)}."
            )

    # --- Mine ---
    multiplier = await get_mining_multiplier(session, user_id)
    amount = int(random.randint(MINING_MIN, MINING_MAX) * multiplier)
    user.bio_coins += amount

    tx = ResourceTransaction(
        user_id=user_id,
        amount=amount,
        currency=CurrencyType.BIO_COINS,
        reason=TransactionReason.MINING,
    )
    session.add(tx)
    await session.flush()

    return amount, f"Добыто {amount} 🧫 BioCoins! Баланс: {user.bio_coins} 🧫 BioCoins."


async def claim_daily_bonus(
    session: AsyncSession, user_id: int
) -> tuple[int, str]:
    """
    Claim the daily bonus for *user_id*.

    Streak logic (derived from DAILY_BONUS transactions):
      - If the last bonus was claimed between 24 h and 48 h ago → streak continues.
      - If more than 48 h have passed               → streak resets to 1.
      - First ever claim                             → streak = 1.

    Returns (amount, message).
    """
    user = await _get_user(session, user_id)
    if user is None:
        return 0, "Пользователь не найден."

    last_tx = await _last_transaction(session, user_id, TransactionReason.DAILY_BONUS)
    now = _now_utc()

    # --- Cooldown check ---
    if last_tx is not None:
        seconds = _seconds_left(last_tx.created_at, DAILY_COOLDOWN)
        if seconds > 0:
            return 0, (
                f"Ежедневный бонус уже получен. "
                f"Следующий через {_fmt_cooldown(seconds)}."
            )

    # --- Streak calculation ---
    # We derive streak from the amount stored in the previous transaction.
    # Simpler approach: look at all DAILY_BONUS transactions and count consecutive
    # calendar days. Here we use the compact two-tx approach.
    if last_tx is None:
        # First ever claim.
        new_streak = 1
    else:
        hours_since = (now - last_tx.created_at).total_seconds() / 3600
        if hours_since <= 48:
            # Continuing streak — decode old streak from metadata stored in amount.
            # We embed the streak inside the tx note via a separate query of all
            # DAILY_BONUS txs ordered by date; but to keep it simple and not add a
            # note column, we derive the streak by counting consecutive-day txs.
            new_streak = await _compute_streak(session, user_id, now) + 1
        else:
            new_streak = 1

    new_streak = min(new_streak, DAILY_STREAK_MAX)
    streak_multiplier = 1.0 + DAILY_STREAK_BONUS * (new_streak - 1)
    premium_multiplier = await get_daily_multiplier(session, user_id)
    amount = int(DAILY_BASE * streak_multiplier * premium_multiplier)

    user.bio_coins += amount

    tx = ResourceTransaction(
        user_id=user_id,
        amount=amount,
        currency=CurrencyType.BIO_COINS,
        reason=TransactionReason.DAILY_BONUS,
    )
    session.add(tx)
    await session.flush()

    streak_msg = (
        f" (стрик: {new_streak} дн., +{int((streak_multiplier - 1) * 100)}%)"
        if new_streak > 1
        else ""
    )
    return amount, (
        f"Ежедневный бонус получен! +{amount} 🧫 BioCoins{streak_msg}. "
        f"Баланс: {user.bio_coins} 🧫 BioCoins."
    )


async def _compute_streak(
    session: AsyncSession, user_id: int, now: datetime
) -> int:
    """
    Count how many consecutive days (before today) the user claimed daily bonus.
    Returns the current streak length (not counting today's pending claim).
    """
    result = await session.execute(
        select(ResourceTransaction)
        .where(
            ResourceTransaction.user_id == user_id,
            ResourceTransaction.reason == TransactionReason.DAILY_BONUS,
        )
        .order_by(desc(ResourceTransaction.created_at))
    )
    txs = result.scalars().all()

    if not txs:
        return 0

    streak = 0
    expected_date = now.date() - timedelta(days=1)

    for tx in txs:
        tx_date = tx.created_at.date()
        if tx_date == expected_date:
            streak += 1
            expected_date -= timedelta(days=1)
        elif tx_date < expected_date:
            # Gap found — streak is broken.
            break
        # tx_date > expected_date can happen for same-day duplicates; skip.

    return streak


async def get_balance(session: AsyncSession, user_id: int) -> dict:
    """
    Return current balance for *user_id*.

    Result keys: bio_coins, premium_coins.
    Returns an empty dict if the user does not exist.
    """
    user = await _get_user(session, user_id)
    if user is None:
        return {}
    return {
        "bio_coins": user.bio_coins,
        "premium_coins": user.premium_coins,
    }
