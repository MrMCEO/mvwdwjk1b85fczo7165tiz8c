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
from html import escape

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
from bot.services.player import DEFAULT_VIRUS_NAME
from bot.services.premium import get_attack_cooldown, get_attack_limits

# Base damage per tick before lethality adjustments
BASE_DAMAGE_PER_TICK: float = 5.0

# Virus names that are considered "not custom" — used to decide whether to show
# the virus name in attack/infection messages.
_NON_CUSTOM: frozenset[str] = frozenset({"", "—", DEFAULT_VIRUS_NAME})

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
) -> tuple[bool, str, dict | None]:
    """
    Attempt to infect *victim_id* using *attacker_id*'s virus.

    Returns (success, message, victim_notification) where:
    - message contains human-readable details for the attacker.
    - victim_notification is a dict {"user_id": int, "message": str} to be sent
      to the victim on success, or None on failure.
    """

    # --- Self-attack guard ---
    if attacker_id == victim_id:
        return False, "Нельзя атаковать самого себя.", None

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
        ), None

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
        ), None

    # --- Check both players exist ---
    # Lock attacker row to prevent concurrent attacks from the same user
    attacker = await _get_user(session, attacker_id, lock=True)
    if attacker is None:
        return False, "Атакующий игрок не найден. Создай профиль через /start.", None

    victim = await _get_user(session, victim_id)
    if victim is None:
        return False, "Жертва не найдена.", None

    # --- Newbie protection: 24 hours after account creation ---
    if victim.created_at and (_now_utc() - victim.created_at) < timedelta(hours=24):
        return False, "🛡 Этот игрок под защитой новичка (24 часа).", None

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
            ), None

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
        return False, "Этот игрок уже заражён твоим вирусом.", None

    # --- Load attacker's virus with upgrades ---
    virus, virus_upgrades = await _load_virus_with_upgrades(session, attacker_id)
    if virus is None:
        return False, "У тебя ещё нет вируса. Используй /start, чтобы создать профиль.", None

    # --- Load victim's immunity with upgrades ---
    immunity, immunity_upgrades = await _load_immunity_with_upgrades(session, victim_id)
    if immunity is None:
        return False, "У жертвы ещё нет иммунитета.", None

    # --- Load victim's virus upgrades (needed for min_balance calculation) ---
    victim_virus, _ = await _load_virus_with_upgrades(session, victim_id)

    # --- Compute total levels for new formulas ---
    # virus_level = sum of all attacker's virus branch levels
    virus_level: int = sum(u.level for u in virus.upgrades)
    # immunity_level = sum of all defender's immunity branch levels
    immunity_level: int = sum(u.level for u in immunity.upgrades)
    # victim_virus_total = sum of all victim's virus branch levels
    victim_virus_total: int = sum(u.level for u in victim_virus.upgrades) if victim_virus else 0

    # --- STEALTH for detection notification logic ---
    stealth_effect = _upgrade_effect(virus_upgrades, VirusBranch.STEALTH)
    detection_effect = _upgrade_effect(immunity_upgrades, ImmunityBranch.DETECTION)
    effective_detection = max(0.0, (immunity.detection_power + detection_effect) - stealth_effect)

    # --- Event modifiers ---
    can_attack = await get_event_modifier(session, "can_attack")
    if not can_attack:
        return False, "Сейчас действует перемирие (🕊 Ceasefire). Атаки запрещены.", None

    attack_chance_event_mult = await get_event_modifier(session, "attack_chance_mult")

    # --- Mutation modifiers ---
    atk_mods = await apply_mutation_to_attack(session, attacker_id)
    def_mods = await apply_mutation_to_defense(session, victim_id)

    if def_mods.get("absolute_immunity"):
        return False, "Цель под защитой Абсолютного иммунитета! Атака невозможна.", None

    # --- Alliance bonuses ---
    atk_alliance_bonus = await get_alliance_attack_bonus(session, attacker_id)
    def_alliance_bonus = await get_alliance_defense_bonus(session, victim_id)

    # --- Laboratory item effects ---
    has_bio_bomb = await get_active_item_effect(session, attacker_id, ItemType.BIO_BOMB)
    has_enhancer = await get_active_item_effect(session, attacker_id, ItemType.VIRUS_ENHANCER)
    has_cloak = await get_active_item_effect(session, attacker_id, ItemType.STEALTH_CLOAK)  # noqa: F841
    has_shield = await get_active_item_effect(session, victim_id, ItemType.SHIELD_BOOST)

    # --- Infection probability (new diff-based formula) ---
    # Base: 50% ± 0.7% per level difference. Clamped 3%–97%.
    if has_bio_bomb:
        chance: float = 0.97  # near-guaranteed attack (leave 3% for the unexpected)
    else:
        diff = virus_level - immunity_level
        chance = 0.50 + diff * 0.007
        chance = max(0.03, min(0.97, chance))

        # Apply event multiplier (additive cap to avoid exceeding 0.97)
        if attack_chance_event_mult != 1.0:
            chance = min(0.97, chance * attack_chance_event_mult)

        # Mutations: additive bonus to base chance
        chance += atk_mods.get("chance_bonus", 0.0)
        chance -= def_mods.get("chance_penalty", 0.0) * def_alliance_bonus  # alliance reduces attacker chance
        # Alliance attack bonus: small additive bump
        chance += atk_alliance_bonus * 0.05
        # Shield item reduces attacker chance by 10%
        if has_shield:
            chance -= 0.10
        # Re-clamp after all modifiers
        chance = max(0.03, min(0.97, chance))

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
        ), None

    # --- Risk-based reward for attacker ---
    avg_level = (virus_level + immunity_level) / 2
    risk_multiplier = 1 + (immunity_level - virus_level) / 50
    risk_multiplier = max(0.1, min(5.0, risk_multiplier))
    reward = int(avg_level * 50 * risk_multiplier)
    reward = max(10, reward)

    # Attacker receives reward
    attacker.bio_coins += reward

    # Victim loses same amount (but not below their minimum balance)
    victim_total_level = immunity_level + victim_virus_total  # victim's total upgrade levels
    victim_min_balance = -(victim_total_level * 500)
    victim.bio_coins = max(victim_min_balance, victim.bio_coins - reward)

    # Record transactions
    reward_tx = ResourceTransaction(
        user_id=attacker_id,
        amount=reward,
        currency=CurrencyType.BIO_COINS,
        reason=TransactionReason.INFECTION_INCOME,
    )
    session.add(reward_tx)
    loss_tx = ResourceTransaction(
        user_id=victim_id,
        amount=-reward,
        currency=CurrencyType.BIO_COINS,
        reason=TransactionReason.INFECTION_LOSS,
    )
    session.add(loss_tx)

    # --- Calculate damage_per_tick ---
    # Lethality increases base damage (+2.0 per level; lvl10 = 25 total)
    lethality_effect = _upgrade_effect(virus_upgrades, VirusBranch.LETHALITY)
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

    # Virus display suffix — shown only when a custom name is set.
    # Default/unset names: None, empty string, "—" (em-dash placeholder), or DEFAULT_VIRUS_NAME.
    virus_display = ""
    if virus.name and virus.name not in _NON_CUSTOM:
        virus_display = f" вирусом «{escape(virus.name)}»"

    victim_display = escape(victim.username or str(victim_id))
    attacker_display = escape(attacker.username or str(attacker_id))

    # Victim sees the attacker only when effective_detection > 0
    # (base detection_power=0.1 means most players are detected unless attacker maxes STEALTH)
    if effective_detection > 0.0:
        victim_notification: dict = {
            "user_id": victim_id,
            "notify_type": "attacks",
            "message": (
                f"⚠️ Вас заразил{virus_display} игрок @{attacker_display}! "
                f"Потеряно {reward} 🧫 BioCoins."
            ),
        }
    else:
        victim_notification = {
            "user_id": victim_id,
            "notify_type": "attacks",
            "message": (
                f"⚠️ Вас заразили{virus_display}! Атакующий неизвестен. "
                f"Потеряно {reward} 🧫 BioCoins."
            ),
        }

    return True, (
        f"✅ Атака{virus_display} на @{victim_display} успешна! "
        f"Шанс был {chance * 100:.1f}%, урон в тик: {damage_per_tick:.1f} 🧫 BioCoins. "
        f"Получено {reward} 🧫 BioCoins."
    ), victim_notification


async def get_random_target(session: AsyncSession, attacker_id: int) -> User | None:
    """Choose a random player to attack.

    Excludes:
    - the attacker themselves
    - players already actively infected by this attacker
    - players who have no immunity record (attack_player would fail for them)
    """
    # Subquery: victim_ids already infected by attacker (active infections only)
    already_infected_sq = (
        select(Infection.victim_id)
        .where(
            and_(
                Infection.attacker_id == attacker_id,
                Infection.is_active == True,  # noqa: E712
            )
        )
        .scalar_subquery()
    )

    # Subquery: user_ids that have an immunity record
    has_immunity_sq = select(Immunity.owner_id).scalar_subquery()

    result = await session.execute(
        select(User)
        .where(
            and_(
                User.tg_id != attacker_id,
                User.tg_id.not_in(already_infected_sq),
                User.tg_id.in_(has_immunity_sq),
            )
        )
        .options(
            selectinload(User.virus),
            selectinload(User.immunity),
        )
        .order_by(func.random())
        .limit(1)
    )
    return result.scalar_one_or_none()


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
