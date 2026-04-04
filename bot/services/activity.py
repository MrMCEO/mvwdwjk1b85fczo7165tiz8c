"""
Activity service — attack log and transaction history for a player.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models.infection import Infection
from bot.models.resource import ResourceTransaction

# Human-readable labels for transaction reasons
_REASON_LABELS: dict[str, str] = {
    "MINING": "⛏ Добыча ресурсов",
    "INFECTION_INCOME": "🦠 Доход от заражения",
    "INFECTION_LOSS": "💀 Потери от заражения",
    "UPGRADE": "🔬 Прокачка",
    "DONATION": "💎 Донат",
    "DAILY_BONUS": "📅 Ежедневный бонус",
}

_CURRENCY_LABELS: dict[str, str] = {
    "BIO_COINS": "🧫 bio_coins",
    "PREMIUM_COINS": "💎 premium",
}


async def get_attack_log(
    session: AsyncSession,
    user_id: int,
    limit: int = 20,
) -> list[dict]:
    """
    Return the last *limit* attacks involving *user_id* (both sent and received),
    ordered by most recent first.

    Each entry:
        {
            type: "sent" | "received",
            opponent_id: int,
            opponent_username: str,
            started_at: datetime,
            is_active: bool,
            damage_per_tick: float,
        }
    """
    # Load infections with the related attacker/victim for username lookup
    stmt = (
        select(Infection)
        .where(
            or_(
                Infection.attacker_id == user_id,
                Infection.victim_id == user_id,
            )
        )
        .options(
            selectinload(Infection.attacker),
            selectinload(Infection.victim),
        )
        .order_by(Infection.started_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    infections = list(result.scalars().all())

    entries: list[dict] = []
    for inf in infections:
        if inf.attacker_id == user_id:
            entry_type = "sent"
            opponent = inf.victim
        else:
            entry_type = "received"
            opponent = inf.attacker

        opponent_username = (
            opponent.username if opponent and opponent.username else str(
                inf.victim_id if entry_type == "sent" else inf.attacker_id
            )
        )
        entries.append(
            {
                "type": entry_type,
                "opponent_id": opponent.tg_id if opponent else 0,
                "opponent_username": opponent_username,
                "started_at": inf.started_at,
                "is_active": inf.is_active,
                "damage_per_tick": inf.damage_per_tick,
            }
        )
    return entries


async def get_transaction_log(
    session: AsyncSession,
    user_id: int,
    limit: int = 20,
) -> list[dict]:
    """
    Return the last *limit* resource transactions for *user_id*,
    ordered by most recent first.

    Each entry:
        {
            amount: int,
            currency: str,          # human-readable label
            currency_raw: str,      # enum value (BIO_COINS / PREMIUM_COINS)
            reason: str,            # human-readable label
            reason_raw: str,        # enum value
            created_at: datetime,
        }
    """
    stmt = (
        select(ResourceTransaction)
        .where(ResourceTransaction.user_id == user_id)
        .order_by(ResourceTransaction.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    transactions = list(result.scalars().all())

    entries: list[dict] = []
    for tx in transactions:
        currency_raw = tx.currency.value
        reason_raw = tx.reason.value
        entries.append(
            {
                "amount": tx.amount,
                "currency": _CURRENCY_LABELS.get(currency_raw, currency_raw),
                "currency_raw": currency_raw,
                "reason": _REASON_LABELS.get(reason_raw, reason_raw),
                "reason_raw": reason_raw,
                "created_at": tx.created_at,
            }
        )
    return entries
