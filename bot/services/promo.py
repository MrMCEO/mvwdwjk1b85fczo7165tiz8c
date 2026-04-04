"""
Promo code service — creation, activation, management.

Promo codes are case-insensitive: stored in uppercase, matched with upper().
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.promo import PromoActivation, PromoCode
from bot.models.resource import Currency as CurrencyType
from bot.models.resource import ResourceTransaction, TransactionReason
from bot.models.user import User

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def create_promo(
    session: AsyncSession,
    code: str,
    bio_coins: int,
    premium_coins: int,
    max_activations: int,
    created_by: int,
    expires_hours: int | None = None,
) -> tuple[bool, str]:
    """
    Create a new promo code.

    Returns (True, "success message") or (False, "error message").
    Code is stored in uppercase for case-insensitive matching.
    """
    normalized = code.strip().upper()
    if not normalized:
        return False, "Код не может быть пустым."
    if len(normalized) > 32:
        return False, "Код слишком длинный (максимум 32 символа)."
    if bio_coins < 0 or premium_coins < 0:
        return False, "Значения валюты не могут быть отрицательными."

    # Check uniqueness (case-insensitive via stored uppercase)
    existing = await session.execute(
        select(PromoCode).where(PromoCode.code == normalized)
    )
    if existing.scalar_one_or_none() is not None:
        return False, f"Промокод <b>{normalized}</b> уже существует."

    expires_at: datetime | None = None
    if expires_hours is not None and expires_hours > 0:
        expires_at = _now_utc() + timedelta(hours=expires_hours)

    promo = PromoCode(
        code=normalized,
        bio_coins=bio_coins,
        premium_coins=premium_coins,
        max_activations=max_activations,
        current_activations=0,
        created_by=created_by,
        expires_at=expires_at,
        is_active=True,
    )
    session.add(promo)
    await session.flush()

    limit_str = str(max_activations) if max_activations > 0 else "∞"
    expires_str = (
        expires_at.strftime("%d.%m.%Y %H:%M") if expires_at else "бессрочно"
    )
    logger.info(
        "Admin %d created promo %r: bio=%d premium=%d max=%s expires=%s",
        created_by,
        normalized,
        bio_coins,
        premium_coins,
        limit_str,
        expires_str,
    )
    return True, (
        f"Промокод <b>{normalized}</b> создан!\n"
        f"🧫 BioCoins: {bio_coins:,} | 💎 PremiumCoins: {premium_coins:,}\n"
        f"Лимит активаций: {limit_str}\n"
        f"Действует до: {expires_str}"
    )


async def activate_promo(
    session: AsyncSession,
    user_id: int,
    code: str,
) -> tuple[bool, str]:
    """
    Activate a promo code for a user.

    Checks:
      - Code exists
      - is_active == True
      - Not expired
      - max_activations not exceeded (0 = unlimited)
      - User has not activated this promo before

    On success: credits bio/premium coins, records transaction and activation.
    Returns (success, message).
    """
    normalized = code.strip().upper()

    # Find promo
    result = await session.execute(
        select(PromoCode).where(PromoCode.code == normalized).with_for_update()
    )
    promo = result.scalar_one_or_none()

    if promo is None:
        return False, "Промокод не найден."

    if not promo.is_active:
        return False, "Промокод неактивен."

    now = _now_utc()
    if promo.expires_at is not None and now > promo.expires_at:
        return False, "Срок действия промокода истёк."

    if promo.max_activations > 0 and promo.current_activations >= promo.max_activations:
        return False, "Промокод больше не доступен (лимит активаций исчерпан)."

    # Check user already activated
    already = await session.execute(
        select(PromoActivation).where(
            PromoActivation.promo_id == promo.id,
            PromoActivation.user_id == user_id,
        )
    )
    if already.scalar_one_or_none() is not None:
        return False, "Ты уже активировал этот промокод."

    # Check user exists
    user_result = await session.execute(
        select(User).where(User.tg_id == user_id).with_for_update()
    )
    user = user_result.scalar_one_or_none()
    if user is None:
        return False, "Пользователь не найден. Начни игру командой /start."

    # Credit coins
    bio_gained = promo.bio_coins
    premium_gained = promo.premium_coins

    if bio_gained > 0:
        user.bio_coins += bio_gained
        tx_bio = ResourceTransaction(
            user_id=user_id,
            amount=bio_gained,
            currency=CurrencyType.BIO_COINS,
            reason=TransactionReason.DONATION,
        )
        session.add(tx_bio)

    if premium_gained > 0:
        user.premium_coins += premium_gained
        tx_premium = ResourceTransaction(
            user_id=user_id,
            amount=premium_gained,
            currency=CurrencyType.PREMIUM_COINS,
            reason=TransactionReason.DONATION,
        )
        session.add(tx_premium)

    # Record activation
    activation = PromoActivation(promo_id=promo.id, user_id=user_id)
    session.add(activation)

    promo.current_activations += 1

    try:
        # Use a savepoint so that an IntegrityError only rolls back this
        # operation and not the entire middleware-managed transaction.
        async with session.begin_nested():
            await session.flush()
    except IntegrityError:
        # Race condition: duplicate activation — savepoint was rolled back,
        # outer transaction is still intact.
        return False, "Ты уже активировал этот промокод."

    parts = []
    if bio_gained > 0:
        parts.append(f"+{bio_gained:,} 🧫 BioCoins")
    if premium_gained > 0:
        parts.append(f"+{premium_gained:,} 💎 PremiumCoins")
    reward_str = ", ".join(parts) if parts else "без валюты"

    logger.info(
        "User %d activated promo %r: bio=%d premium=%d",
        user_id,
        normalized,
        bio_gained,
        premium_gained,
    )
    return True, (
        f"Промокод <b>{normalized}</b> активирован!\n"
        f"{reward_str}\n\n"
        f"Твой баланс: {user.bio_coins:,} 🧫 BioCoins | {user.premium_coins:,} 💎 PremiumCoins"
    )


async def delete_promo(session: AsyncSession, code: str) -> tuple[bool, str]:
    """
    Deactivate (soft-delete) a promo code by code string.

    Returns (success, message).
    """
    normalized = code.strip().upper()
    result = await session.execute(
        select(PromoCode).where(PromoCode.code == normalized)
    )
    promo = result.scalar_one_or_none()

    if promo is None:
        return False, f"Промокод <b>{normalized}</b> не найден."

    if not promo.is_active:
        return False, f"Промокод <b>{normalized}</b> уже деактивирован."

    promo.is_active = False
    await session.flush()

    logger.info("Promo %r deactivated.", normalized)
    return True, f"Промокод <b>{normalized}</b> деактивирован."


async def list_promos(session: AsyncSession, limit: int = 20) -> list[dict]:
    """
    Return a list of all promo codes (newest first) with statistics.

    Each dict: code, bio_coins, premium_coins, max_activations,
               current_activations, is_active, expires_at, created_at.
    """
    result = await session.execute(
        select(PromoCode)
        .order_by(PromoCode.created_at.desc())
        .limit(limit)
    )
    promos = result.scalars().all()

    now = _now_utc()
    out = []
    for p in promos:
        expired = p.expires_at is not None and now > p.expires_at
        out.append(
            {
                "id": p.id,
                "code": p.code,
                "bio_coins": p.bio_coins,
                "premium_coins": p.premium_coins,
                "max_activations": p.max_activations,
                "current_activations": p.current_activations,
                "is_active": p.is_active,
                "expired": expired,
                "expires_at": p.expires_at,
                "created_at": p.created_at,
            }
        )
    return out


async def get_promo_info(session: AsyncSession, code: str) -> dict | None:
    """
    Return detailed info about a promo code including activation list.

    Returns None if code not found.
    """
    normalized = code.strip().upper()
    result = await session.execute(
        select(PromoCode).where(PromoCode.code == normalized)
    )
    promo = result.scalar_one_or_none()
    if promo is None:
        return None

    # Get activation records with user info
    activations_result = await session.execute(
        select(PromoActivation, User)
        .join(User, User.tg_id == PromoActivation.user_id)
        .where(PromoActivation.promo_id == promo.id)
        .order_by(PromoActivation.activated_at.desc())
        .limit(50)
    )
    rows = activations_result.all()

    activations = [
        {
            "user_id": row.User.tg_id,
            "username": row.User.username or str(row.User.tg_id),
            "activated_at": row.PromoActivation.activated_at,
        }
        for row in rows
    ]

    now = _now_utc()
    expired = promo.expires_at is not None and now > promo.expires_at

    return {
        "id": promo.id,
        "code": promo.code,
        "bio_coins": promo.bio_coins,
        "premium_coins": promo.premium_coins,
        "max_activations": promo.max_activations,
        "current_activations": promo.current_activations,
        "is_active": promo.is_active,
        "expired": expired,
        "expires_at": promo.expires_at,
        "created_at": promo.created_at,
        "activations": activations,
    }
