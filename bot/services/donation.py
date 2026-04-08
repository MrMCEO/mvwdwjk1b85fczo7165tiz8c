"""
Donation service — premium coins management and conversion.

Design principle: premium coins give convenience and speed, NOT absolute advantage.

EXCHANGE_RATE: how many bio_coins 1 premium_coin is worth.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.resource import (
    Currency as CurrencyType,
)
from bot.models.resource import (
    ResourceTransaction,
    TransactionReason,
)
from bot.models.user import User

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXCHANGE_RATE: int = 15  # 1 premium_coin = 15 bio_coins

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _get_user(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(
        select(User).where(User.tg_id == user_id).with_for_update()
    )
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def convert_premium_to_bio(
    session: AsyncSession,
    user_id: int,
    amount: int,
) -> tuple[bool, str]:
    """
    Convert *amount* premium_coins into bio_coins for *user_id*.

    Exchange rate: 1 premium_coin → EXCHANGE_RATE bio_coins.

    Returns (success, message).
    """
    if amount <= 0:
        return False, "Количество должно быть больше нуля."

    user = await _get_user(session, user_id)
    if user is None:
        return False, "Пользователь не найден."

    if user.premium_coins < amount:
        return False, (
            f"Недостаточно 💎 PremiumCoins. "
            f"Нужно {amount}, у тебя {user.premium_coins}."
        )

    bio_gained = amount * EXCHANGE_RATE
    user.premium_coins -= amount
    user.bio_coins += bio_gained

    # Record the spend of premium_coins
    tx_premium = ResourceTransaction(
        user_id=user_id,
        amount=-amount,
        currency=CurrencyType.PREMIUM_COINS,
        reason=TransactionReason.DONATION,
    )
    # Record the gain of bio_coins
    tx_bio = ResourceTransaction(
        user_id=user_id,
        amount=bio_gained,
        currency=CurrencyType.BIO_COINS,
        reason=TransactionReason.DONATION,
    )
    session.add(tx_premium)
    session.add(tx_bio)
    await session.flush()

    return True, (
        f"Конвертировано {amount} 💎 PremiumCoins → {bio_gained} 🧫 BioCoins "
        f"(курс 1:{EXCHANGE_RATE}). "
        f"Баланс: {user.bio_coins} 🧫 | {user.premium_coins} 💎."
    )


async def add_premium_coins(
    session: AsyncSession,
    user_id: int,
    amount: int,
) -> None:
    """
    Add *amount* premium_coins to *user_id*.

    This is a stub for future payment integration (Telegram Stars / other).
    Call this after a successful payment confirmation from the payment provider.
    """
    # TODO: integrate with Telegram Stars / payment provider webhook.
    #       Validate that the payment was actually completed before calling this.

    if amount <= 0:
        raise ValueError(f"amount must be positive, got {amount}")

    user = await _get_user(session, user_id)
    if user is None:
        raise LookupError(f"User {user_id} not found.")

    user.premium_coins += amount

    tx = ResourceTransaction(
        user_id=user_id,
        amount=amount,
        currency=CurrencyType.PREMIUM_COINS,
        reason=TransactionReason.DONATION,
    )
    session.add(tx)
    await session.flush()
