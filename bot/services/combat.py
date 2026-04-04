"""
Combat service — attack, infection management, and manual cure logic.

Attack flow:
  1. Validate: no self-attack, attacker not on cooldown, victim not already
     infected by this attacker.
  2. Load attacker's Virus + all VirusUpgrades.
  3. Load victim's Immunity + all ImmunityUpgrades.
  4. Calculate attack_score and defense_score with branch bonuses.
  5. Roll random() against the resulting probability.
  6. On success: create Infection row with computed damage_per_tick.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models.immunity import Immunity, ImmunityBranch, ImmunityUpgrade
from bot.models.infection import Infection
from bot.models.resource import Currency as CurrencyType
from bot.models.resource import ResourceTransaction, TransactionReason
from bot.models.user import User
from bot.models.virus import Virus, VirusBranch, VirusUpgrade

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ATTACK_COOLDOWN = timedelta(minutes=30)

# Base damage per tick before lethality / regen adjustments
BASE_DAMAGE_PER_TICK: float = 5.0

# Cure cost = damage_per_tick * this multiplier (rounded up)
CURE_COST_MULTIPLIER: float = 10.0

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    """Return current naive UTC datetime (stored without tzinfo in DB)."""
    return datetime.now(UTC).replace(tzinfo=None)


async def _get_user(session: AsyncSession, user_id: int, lock: bool = False) -> User | None:
    stmt = select(User).where(User.tg_id == user_id)
    if lock:
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def _load_virus_with_upgrades(session: AsyncSession, user_id: int):
    """Return (Virus, dict[VirusBranch, VirusUpgrade]) or (None, {})."""
    result = await session.execute(
        select(Virus)
        .where(Virus.owner_id == user_id)
        .options(selectinload(Virus.upgrades))
    )
    virus = result.scalar_one_or_none()
    if virus is None:
        return None, {}

    upgrades_by_branch: dict[VirusBranch, VirusUpgrade] = {
        u.branch: u for u in virus.upgrades
    }
    return virus, upgrades_by_branch


async def _load_immunity_with_upgrades(session: AsyncSession, user_id: int):
    """Return (Immunity, dict[ImmunityBranch, ImmunityUpgrade]) or (None, {})."""
    result = await session.execute(
        select(Immunity)
        .where(Immunity.owner_id == user_id)
        .options(selectinload(Immunity.upgrades))
    )
    immunity = result.scalar_one_or_none()
    if immunity is None:
        return None, {}

    upgrades_by_branch: dict[ImmunityBranch, ImmunityUpgrade] = {
        u.branch: u for u in immunity.upgrades
    }
    return immunity, upgrades_by_branch


def _upgrade_effect(upgrades: dict, branch) -> float:
    """Return effect_value of the given branch, or 0.0 if not present / level 0."""
    u = upgrades.get(branch)
    if u is None or u.level == 0:
        return 0.0
    return u.effect_value


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def attack_player(
    session: AsyncSession,
    attacker_id: int,
    victim_id: int,
) -> tuple[bool, str]:
    """
    Attempt to infect *victim_id* using *attacker_id*'s virus.

    Returns (success, message) where message contains human-readable details
    about the outcome regardless of success/failure.
    """

    # --- Self-attack guard ---
    if attacker_id == victim_id:
        return False, "Нельзя атаковать самого себя."

    # --- Check both players exist ---
    # Lock attacker row to prevent concurrent attacks from the same user
    attacker = await _get_user(session, attacker_id, lock=True)
    if attacker is None:
        return False, "Атакующий игрок не найден. Создай профиль через /start."

    victim = await _get_user(session, victim_id)
    if victim is None:
        return False, "Жертва не найдена."

    # --- Cooldown: look at last infection this attacker has sent (any victim) ---
    last_attack_result = await session.execute(
        select(Infection)
        .where(Infection.attacker_id == attacker_id)
        .order_by(Infection.started_at.desc())
        .limit(1)
    )
    last_attack = last_attack_result.scalar_one_or_none()
    if last_attack is not None:
        now = _now_utc()
        elapsed = now - last_attack.started_at
        if elapsed < ATTACK_COOLDOWN:
            remaining = ATTACK_COOLDOWN - elapsed
            minutes = int(remaining.total_seconds() // 60)
            seconds = int(remaining.total_seconds() % 60)
            return False, (
                f"Кулдаун атаки ещё не истёк. "
                f"Следующая атака через {minutes}м {seconds}с."
            )

    # --- Victim already infected by this attacker? ---
    already_infected_result = await session.execute(
        select(Infection).where(
            and_(
                Infection.attacker_id == attacker_id,
                Infection.victim_id == victim_id,
                Infection.is_active == True,  # noqa: E712
            )
        ).with_for_update()
    )
    already_infected = already_infected_result.scalar_one_or_none()
    if already_infected is not None:
        return False, "Этот игрок уже заражён твоим вирусом."

    # --- Load attacker's virus with upgrades ---
    virus, virus_upgrades = await _load_virus_with_upgrades(session, attacker_id)
    if virus is None:
        return False, "У тебя ещё нет вируса. Используй /start, чтобы создать профиль."

    # --- Load victim's immunity with upgrades ---
    immunity, immunity_upgrades = await _load_immunity_with_upgrades(session, victim_id)
    if immunity is None:
        return False, "У жертвы ещё нет иммунитета."

    # --- Attack score ---
    # Base: attack_power * spread_rate
    attack_score: float = virus.attack_power * virus.spread_rate

    # CONTAGION bonus: multiplies attack score
    contagion_effect = _upgrade_effect(virus_upgrades, VirusBranch.CONTAGION)
    attack_score *= 1.0 + contagion_effect

    # STEALTH reduces victim's effective detection_power (used for defense_score calc)
    stealth_effect = _upgrade_effect(virus_upgrades, VirusBranch.STEALTH)
    effective_detection = max(0.0, immunity.detection_power - stealth_effect)

    # --- Defense score ---
    # Base: resistance * (1 + BARRIER effect_value)
    barrier_effect = _upgrade_effect(immunity_upgrades, ImmunityBranch.BARRIER)
    defense_score: float = immunity.resistance * (1.0 + barrier_effect)

    # Detection adds a small bonus to defense when the attacker is not stealthed out
    defense_score += effective_detection * immunity.resistance * 0.1

    # --- Infection probability ---
    total = attack_score + defense_score
    chance: float = attack_score / total if total > 0 else 0.0
    chance = max(0.0, min(1.0, chance))

    roll = random.random()
    success = roll < chance

    if not success:
        return False, (
            f"Атака провалилась! "
            f"Шанс заражения был {chance * 100:.1f}% (бросок: {roll * 100:.1f}%). "
            f"Иммунитет жертвы устоял."
        )

    # --- Calculate damage_per_tick ---
    # Lethality increases base damage
    lethality_effect = _upgrade_effect(virus_upgrades, VirusBranch.LETHALITY)
    # Regeneration reduces incoming damage
    regen_effect = _upgrade_effect(immunity_upgrades, ImmunityBranch.REGENERATION)

    damage_per_tick = max(1.0, BASE_DAMAGE_PER_TICK + lethality_effect - regen_effect)

    # --- Create Infection ---
    infection = Infection(
        attacker_id=attacker_id,
        victim_id=victim_id,
        started_at=_now_utc(),
        damage_per_tick=damage_per_tick,
        is_active=True,
    )
    session.add(infection)
    await session.flush()

    victim_display = victim.username or str(victim_id)
    return True, (
        f"Атака успешна! Игрок {victim_display} заражён. "
        f"Шанс был {chance * 100:.1f}%, урон в тик: {damage_per_tick:.1f} bio_coins."
    )


async def get_active_infections_by(
    session: AsyncSession,
    user_id: int,
) -> list[Infection]:
    """Return all active outgoing infections sent by *user_id*."""
    result = await session.execute(
        select(Infection)
        .where(
            and_(
                Infection.attacker_id == user_id,
                Infection.is_active == True,  # noqa: E712
            )
        )
        .order_by(Infection.started_at.desc())
    )
    return list(result.scalars().all())


async def get_active_infections_on(
    session: AsyncSession,
    user_id: int,
) -> list[Infection]:
    """Return all active incoming infections targeting *user_id*."""
    result = await session.execute(
        select(Infection)
        .where(
            and_(
                Infection.victim_id == user_id,
                Infection.is_active == True,  # noqa: E712
            )
        )
        .order_by(Infection.started_at.desc())
    )
    return list(result.scalars().all())


async def try_cure(
    session: AsyncSession,
    user_id: int,
    infection_id: int,
) -> tuple[bool, str]:
    """
    Manually cure an active infection on *user_id* by spending bio_coins.

    Cost = ceil(damage_per_tick * CURE_COST_MULTIPLIER).
    Deactivates the Infection row and records a ResourceTransaction.

    Returns (success, message).
    """
    # Load infection and verify ownership — lock the row to prevent double-cure
    result = await session.execute(
        select(Infection).where(
            and_(
                Infection.id == infection_id,
                Infection.victim_id == user_id,
                Infection.is_active == True,  # noqa: E712
            )
        ).with_for_update()
    )
    infection = result.scalar_one_or_none()
    if infection is None:
        return False, "Активное заражение не найдено."

    # Load victim (payer) — lock to prevent concurrent balance changes
    user = await _get_user(session, user_id, lock=True)
    if user is None:
        return False, "Пользователь не найден."

    cost = math.ceil(infection.damage_per_tick * CURE_COST_MULTIPLIER)

    if user.bio_coins < cost:
        return False, (
            f"Недостаточно bio_coins для лечения. "
            f"Нужно {cost}, у тебя {user.bio_coins}."
        )

    # Deduct cost and deactivate
    user.bio_coins -= cost
    infection.is_active = False

    tx = ResourceTransaction(
        user_id=user_id,
        amount=-cost,
        currency=CurrencyType.BIO_COINS,
        reason=TransactionReason.INFECTION_LOSS,
    )
    session.add(tx)
    await session.flush()

    return True, (
        f"Заражение #{infection_id} успешно вылечено! "
        f"Потрачено {cost} bio_coins. Баланс: {user.bio_coins} bio_coins."
    )
