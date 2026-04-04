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

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models.attack_log import AttackAttempt
from bot.models.immunity import Immunity, ImmunityBranch, ImmunityUpgrade
from bot.models.infection import Infection
from bot.models.item import ItemType
from bot.models.resource import Currency as CurrencyType
from bot.models.resource import ResourceTransaction, TransactionReason
from bot.models.user import User
from bot.models.virus import Virus, VirusBranch, VirusUpgrade
from bot.services.alliance import get_alliance_attack_bonus, get_alliance_defense_bonus
from bot.services.event import get_event_modifier
from bot.services.laboratory import get_active_item_effect
from bot.services.market import check_contract_completion
from bot.services.mutation_effects import apply_mutation_to_attack, apply_mutation_to_defense
from bot.services.premium import get_attack_cooldown, get_attack_limits

# Base damage per tick before lethality adjustments
BASE_DAMAGE_PER_TICK: float = 5.0

# Cure cost = damage_per_tick * this multiplier (rounded up).
# Lowered from 10 to 8: at base dmg 5, cure = 40 coins. Comparable to expected loss
# of waiting (~5 dmg * ~5 ticks avg = 25), so manual cure is worth it when urgent.
CURE_COST_MULTIPLIER: float = 8.0

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

    # --- Resolve premium-aware limits for the attacker ---
    max_attempts, max_infections = await get_attack_limits(session, attacker_id)

    # --- Rate limit: attempts on the same target per hour ---
    one_hour_ago = _now_utc() - timedelta(hours=1)
    attempts_on_target = await session.execute(
        select(func.count()).select_from(AttackAttempt).where(
            AttackAttempt.attacker_id == attacker_id,
            AttackAttempt.victim_id == victim_id,
            AttackAttempt.attempted_at >= one_hour_ago,
        )
    )
    count = attempts_on_target.scalar_one()
    if count >= max_attempts:
        return False, (
            f"Вы уже атаковали этого игрока {max_attempts} раз за последний час. "
            "Попробуйте позже."
        )

    # --- Rate limit: successful infections per hour (all targets) ---
    successful_infections = await session.execute(
        select(func.count()).select_from(AttackAttempt).where(
            AttackAttempt.attacker_id == attacker_id,
            AttackAttempt.success == True,  # noqa: E712
            AttackAttempt.attempted_at >= one_hour_ago,
        )
    )
    success_count = successful_infections.scalar_one()
    if success_count >= max_infections:
        return False, (
            f"Вы достигли лимита заражений ({max_infections} в час). Попробуйте позже."
        )

    # --- Check both players exist ---
    # Lock attacker row to prevent concurrent attacks from the same user
    attacker = await _get_user(session, attacker_id, lock=True)
    if attacker is None:
        return False, "Атакующий игрок не найден. Создай профиль через /start."

    victim = await _get_user(session, victim_id)
    if victim is None:
        return False, "Жертва не найдена."

    # --- Cooldown: look at last infection this attacker has sent (any victim) ---
    attack_cooldown = await get_attack_cooldown(session, attacker_id)
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
        if elapsed < attack_cooldown:
            remaining = attack_cooldown - elapsed
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
    # Base: attack_power (default 10). spread_rate is now a direct multiplier (default 1.0).
    # Formula: attack_power * spread_rate * (1 + contagion_bonus)
    attack_score: float = virus.attack_power * virus.spread_rate

    # CONTAGION bonus: multiplies attack score (+8% per level)
    contagion_effect = _upgrade_effect(virus_upgrades, VirusBranch.CONTAGION)
    attack_score *= 1.0 + contagion_effect

    # STEALTH reduces victim's effective detection_power
    stealth_effect = _upgrade_effect(virus_upgrades, VirusBranch.STEALTH)

    # --- Defense score ---
    # Base: resistance (default 10). BARRIER adds flat defense (not multiplicative!).
    # Old formula resistance * (1 + barrier) was exponentially broken at high levels.
    barrier_effect = _upgrade_effect(immunity_upgrades, ImmunityBranch.BARRIER)
    defense_score: float = immunity.resistance + barrier_effect  # balanced: additive, not multiplicative

    # Detection adds direct bonus to defense when attacker is not fully stealthed.
    # Scaled by 5.0 so detection upgrades (+0.05/lvl) are meaningful: lvl10 = +2.5 defense.
    detection_effect = _upgrade_effect(immunity_upgrades, ImmunityBranch.DETECTION)
    effective_detection = max(0.0, (immunity.detection_power + detection_effect) - stealth_effect)
    defense_score += effective_detection * 5.0  # balanced: detection matters but not dominant

    # --- Event modifiers ---
    can_attack = await get_event_modifier(session, "can_attack")
    if not can_attack:
        return False, "Сейчас действует перемирие (🕊 Ceasefire). Атаки запрещены."

    attack_chance_mult = await get_event_modifier(session, "attack_chance_mult")
    attack_score *= attack_chance_mult

    defense_mult = await get_event_modifier(session, "defense_mult")
    defense_score *= defense_mult

    # --- Mutation modifiers (attacker) ---
    atk_mods = await apply_mutation_to_attack(session, attacker_id)
    attack_score *= atk_mods.get("attack_mult", 1.0)
    attack_score *= atk_mods.get("spread_mult", 1.0)

    # --- Mutation modifiers (defender) ---
    def_mods = await apply_mutation_to_defense(session, victim_id)
    defense_score *= def_mods.get("defense_mult", 1.0)

    if def_mods.get("absolute_immunity"):
        return False, "Цель под защитой Абсолютного иммунитета! Атака невозможна."

    # --- Alliance bonuses ---
    atk_alliance_bonus = await get_alliance_attack_bonus(session, attacker_id)
    attack_score *= (1.0 + atk_alliance_bonus)

    def_alliance_bonus = await get_alliance_defense_bonus(session, victim_id)
    defense_score *= (1.0 + def_alliance_bonus)

    # --- Laboratory item effects ---
    has_bio_bomb = await get_active_item_effect(session, attacker_id, ItemType.BIO_BOMB)
    has_enhancer = await get_active_item_effect(session, attacker_id, ItemType.VIRUS_ENHANCER)
    has_cloak = await get_active_item_effect(session, attacker_id, ItemType.STEALTH_CLOAK)  # noqa: F841 (reserved for future use)
    has_shield = await get_active_item_effect(session, victim_id, ItemType.SHIELD_BOOST)

    if has_shield:
        defense_score *= 1.5

    # --- Infection probability ---
    # With defaults: attack=10, defense=10+(0.1*5)=10.5, chance=10/20.5=48.8% — close to target 45%
    total = attack_score + defense_score
    if has_bio_bomb:
        chance: float = 0.95  # near-guaranteed attack (leave 5% for the unexpected)
    else:
        chance = attack_score / total if total > 0 else 0.0
        chance = max(0.05, min(0.95, chance))  # floor 5%, cap 95% — always a small chance either way

    roll = random.random()
    success = roll < chance

    if not success:
        # Log the failed attempt
        attempt = AttackAttempt(
            attacker_id=attacker_id,
            victim_id=victim_id,
            success=False,
        )
        session.add(attempt)
        await session.flush()
        return False, (
            f"Атака провалилась! "
            f"Шанс заражения был {chance * 100:.1f}% (бросок: {roll * 100:.1f}%). "
            f"Иммунитет жертвы устоял."
        )

    # --- Calculate damage_per_tick ---
    # Lethality increases base damage (+2.0 per level; lvl10 = 25 total)
    lethality_effect = _upgrade_effect(virus_upgrades, VirusBranch.LETHALITY)
    # Regeneration no longer reduces damage here — it boosts auto-cure chance in tick.py.
    # This makes REGEN and BARRIER serve different roles:
    #   BARRIER = reduce chance of getting infected (prevention)
    #   REGEN   = recover faster once infected (cure speed)

    damage_per_tick = max(1.0, BASE_DAMAGE_PER_TICK + lethality_effect)

    # Virus Enhancer item: double damage for this attack
    if has_enhancer:
        damage_per_tick *= 2.0

    # --- Create Infection ---
    infection = Infection(
        attacker_id=attacker_id,
        victim_id=victim_id,
        started_at=_now_utc(),
        damage_per_tick=damage_per_tick,
        is_active=True,
    )
    session.add(infection)

    # --- Log the successful attempt ---
    attempt = AttackAttempt(
        attacker_id=attacker_id,
        victim_id=victim_id,
        success=True,
    )
    session.add(attempt)
    await session.flush()

    # --- Check hit-contract completion ---
    await check_contract_completion(session, attacker_id, victim_id)

    # Track activity for event leaderboards
    from bot.services.event import track_activity
    await track_activity(session, attacker_id, "attack")

    victim_display = victim.username or str(victim_id)
    return True, (
        f"Атака успешна! Игрок {victim_display} заражён. "
        f"Шанс был {chance * 100:.1f}%, урон в тик: {damage_per_tick:.1f} 🧫 BioCoins."
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
            f"Недостаточно 🧫 BioCoins для лечения. "
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
        f"Потрачено {cost} 🧫 BioCoins. Баланс: {user.bio_coins} 🧫 BioCoins."
    )
