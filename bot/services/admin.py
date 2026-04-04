"""
Admin service — player lookup, balance management, audit logs.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import and_, desc, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models.immunity import Immunity
from bot.models.infection import Infection
from bot.models.resource import Currency as CurrencyType
from bot.models.resource import ResourceTransaction, TransactionReason
from bot.models.user import User
from bot.models.virus import Virus

logger = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Player lookup
# ---------------------------------------------------------------------------


async def lookup_player(session: AsyncSession, identifier: str) -> dict | None:
    """
    Look up a player by tg_id (numeric string) or @username.

    Returns a full profile dict or None if not found.
    Profile structure mirrors get_player_profile() from services/player.py
    but is self-contained here to avoid circular imports.
    """
    identifier = identifier.strip()

    # Determine query type
    if identifier.lstrip("@").isdigit() and not identifier.startswith("@"):
        # Numeric ID
        result = await session.execute(
            select(User)
            .where(User.tg_id == int(identifier))
            .options(
                selectinload(User.virus).selectinload(Virus.upgrades),
                selectinload(User.immunity).selectinload(Immunity.upgrades),
            )
        )
    else:
        # Username (strip leading @)
        uname = identifier.lstrip("@").lower()
        result = await session.execute(
            select(User)
            .where(User.username.ilike(uname))
            .options(
                selectinload(User.virus).selectinload(Virus.upgrades),
                selectinload(User.immunity).selectinload(Immunity.upgrades),
            )
        )

    user = result.scalar_one_or_none()
    if user is None:
        return None

    user_id = user.tg_id

    # Infection counts
    sent_res = await session.execute(
        select(Infection).where(
            and_(Infection.attacker_id == user_id, Infection.is_active == True)  # noqa: E712
        )
    )
    infections_sent = sent_res.scalars().all()

    recv_res = await session.execute(
        select(Infection).where(
            and_(Infection.victim_id == user_id, Infection.is_active == True)  # noqa: E712
        )
    )
    infections_recv = recv_res.scalars().all()

    # Alliance info
    alliance_info: str = "Нет"
    try:
        from bot.models.alliance import Alliance, AllianceMember
        member_res = await session.execute(
            select(AllianceMember, Alliance)
            .join(Alliance, Alliance.id == AllianceMember.alliance_id)
            .where(AllianceMember.user_id == user_id)
        )
        row = member_res.first()
        if row:
            alliance_info = f"[{row.Alliance.tag}] {row.Alliance.name}"
    except Exception:
        pass

    # Virus
    virus_data: dict = {}
    if user.virus:
        v = user.virus
        upgrades = {u.branch.value: {"level": u.level, "effect": u.effect_value} for u in v.upgrades}
        virus_data = {
            "name": v.name,
            "level": v.level,
            "attack_power": v.attack_power,
            "spread_rate": v.spread_rate,
            "mutation_points": v.mutation_points,
            "upgrades": upgrades,
        }

    # Immunity
    immunity_data: dict = {}
    if user.immunity:
        im = user.immunity
        upgrades = {u.branch.value: {"level": u.level, "effect": u.effect_value} for u in im.upgrades}
        immunity_data = {
            "level": im.level,
            "resistance": im.resistance,
            "detection_power": im.detection_power,
            "recovery_speed": im.recovery_speed,
            "upgrades": upgrades,
        }

    return {
        "user": {
            "tg_id": user.tg_id,
            "username": user.username,
            "bio_coins": user.bio_coins,
            "premium_coins": user.premium_coins,
            "created_at": user.created_at,
            "last_active": user.last_active,
        },
        "virus": virus_data,
        "immunity": immunity_data,
        "infections_sent_count": len(infections_sent),
        "infections_received_count": len(infections_recv),
        "alliance": alliance_info,
    }


# ---------------------------------------------------------------------------
# Balance management
# ---------------------------------------------------------------------------


async def set_balance(
    session: AsyncSession,
    user_id: int,
    bio_coins: int | None = None,
    premium_coins: int | None = None,
) -> tuple[bool, str]:
    """
    Set exact balance for a user (not add — SET).

    Creates ResourceTransaction(reason=DONATION) for audit.
    Returns (success, message).
    """
    result = await session.execute(
        select(User).where(User.tg_id == user_id).with_for_update()
    )
    user = result.scalar_one_or_none()
    if user is None:
        return False, f"Игрок {user_id} не найден."

    changes: list[str] = []

    if bio_coins is not None:
        if bio_coins < 0:
            return False, "bio_coins не может быть отрицательным."
        delta_bio = bio_coins - user.bio_coins
        user.bio_coins = bio_coins
        tx = ResourceTransaction(
            user_id=user_id,
            amount=delta_bio,
            currency=CurrencyType.BIO_COINS,
            reason=TransactionReason.DONATION,
        )
        session.add(tx)
        changes.append(f"bio → {bio_coins:,} (delta {delta_bio:+,})")

    if premium_coins is not None:
        if premium_coins < 0:
            return False, "premium_coins не может быть отрицательным."
        delta_prem = premium_coins - user.premium_coins
        user.premium_coins = premium_coins
        tx = ResourceTransaction(
            user_id=user_id,
            amount=delta_prem,
            currency=CurrencyType.PREMIUM_COINS,
            reason=TransactionReason.DONATION,
        )
        session.add(tx)
        changes.append(f"premium → {premium_coins:,} (delta {delta_prem:+,})")

    if not changes:
        return False, "Не указано ни одно значение для изменения."

    await session.flush()
    uname = f"@{user.username}" if user.username else str(user_id)
    logger.info("Admin set_balance for %s: %s", uname, "; ".join(changes))
    return True, (
        f"Баланс игрока {uname} обновлён:\n"
        + "\n".join(f"  • {c}" for c in changes)
    )


async def give_currency(
    session: AsyncSession,
    user_id: int,
    bio_coins: int = 0,
    premium_coins: int = 0,
) -> tuple[bool, str]:
    """
    Add bio_coins and/or premium_coins to a user's current balance.

    Creates ResourceTransaction(reason=DONATION) for audit.
    Returns (success, message).
    """
    if bio_coins == 0 and premium_coins == 0:
        return False, "Не указано ни одно значение для выдачи."

    result = await session.execute(
        select(User).where(User.tg_id == user_id).with_for_update()
    )
    user = result.scalar_one_or_none()
    if user is None:
        return False, f"Игрок {user_id} не найден."

    parts: list[str] = []

    if bio_coins != 0:
        user.bio_coins = max(0, user.bio_coins + bio_coins)
        tx = ResourceTransaction(
            user_id=user_id,
            amount=bio_coins,
            currency=CurrencyType.BIO_COINS,
            reason=TransactionReason.DONATION,
        )
        session.add(tx)
        parts.append(f"{bio_coins:+,} 🧫 bio")

    if premium_coins != 0:
        user.premium_coins = max(0, user.premium_coins + premium_coins)
        tx = ResourceTransaction(
            user_id=user_id,
            amount=premium_coins,
            currency=CurrencyType.PREMIUM_COINS,
            reason=TransactionReason.DONATION,
        )
        session.add(tx)
        parts.append(f"{premium_coins:+,} 💎 premium")

    await session.flush()
    uname = f"@{user.username}" if user.username else str(user_id)
    logger.info("Admin gave %s to %s", ", ".join(parts), uname)
    return True, (
        f"Игроку {uname} выдано: {', '.join(parts)}\n"
        f"Текущий баланс: {user.bio_coins:,} 🧫 | {user.premium_coins:,} 💎"
    )


# ---------------------------------------------------------------------------
# Audit logs
# ---------------------------------------------------------------------------


async def get_player_logs(
    session: AsyncSession,
    user_id: int,
    log_type: str = "all",
    limit: int = 30,
) -> list[dict]:
    """
    Return audit logs for a player.

    log_type values:
      "upgrades"  → ResourceTransaction with reason=UPGRADE
      "purchases" → ResourceTransaction with reason=DONATION
      "attacks"   → Infection records (in + out)
      "all"       → everything, sorted by date desc
    """
    entries: list[dict] = []

    if log_type in ("upgrades", "purchases", "all"):
        reasons: list[TransactionReason] = []
        if log_type == "upgrades":
            reasons = [TransactionReason.UPGRADE]
        elif log_type == "purchases":
            reasons = [TransactionReason.DONATION]
        else:
            reasons = list(TransactionReason)

        tx_result = await session.execute(
            select(ResourceTransaction)
            .where(
                ResourceTransaction.user_id == user_id,
                ResourceTransaction.reason.in_(reasons),
            )
            .order_by(desc(ResourceTransaction.created_at))
            .limit(limit)
        )
        for tx in tx_result.scalars().all():
            sign = "+" if tx.amount >= 0 else ""
            entries.append(
                {
                    "type": "transaction",
                    "subtype": tx.reason.value,
                    "amount": tx.amount,
                    "sign": sign,
                    "currency": tx.currency.value,
                    "date": tx.created_at,
                    "label": (
                        f"{sign}{tx.amount:,} {tx.currency.value}"
                        f" [{tx.reason.value}]"
                    ),
                }
            )

    if log_type in ("attacks", "all"):
        inf_result = await session.execute(
            select(Infection, User)
            .join(
                User,
                or_(
                    and_(Infection.attacker_id == user_id, User.tg_id == Infection.victim_id),
                    and_(Infection.victim_id == user_id, User.tg_id == Infection.attacker_id),
                ),
            )
            .where(
                or_(
                    Infection.attacker_id == user_id,
                    Infection.victim_id == user_id,
                )
            )
            .order_by(desc(Infection.started_at))
            .limit(limit)
        )
        for row in inf_result.all():
            inf: Infection = row.Infection
            other: User = row.User
            other_name = f"@{other.username}" if other.username else str(other.tg_id)
            direction = "→" if inf.attacker_id == user_id else "←"
            active_str = "активно" if inf.is_active else "завершено"
            entries.append(
                {
                    "type": "infection",
                    "direction": direction,
                    "other": other_name,
                    "active": inf.is_active,
                    "damage": inf.damage_per_tick,
                    "date": inf.started_at,
                    "label": (
                        f"Заражение {direction} {other_name}"
                        f" ({active_str}, {inf.damage_per_tick:.1f}/тик)"
                    ),
                }
            )

    # Sort everything by date desc
    entries.sort(key=lambda e: e["date"], reverse=True)
    return entries[:limit]
