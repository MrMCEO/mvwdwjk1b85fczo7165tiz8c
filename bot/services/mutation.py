"""
Mutation service — rolling, querying, expiring, and applying virus mutations.

Mutation flow:
  - After each attack there is a 15% chance to roll a mutation.
  - Rarity is chosen by weighted random (COMMON 60, UNCOMMON 25, RARE 12, LEGENDARY 3).
  - Within the chosen rarity a mutation type is selected uniformly at random.
  - Duration 0 means permanent (used for EVOLUTION_LEAP).
  - DOUBLE_STRIKE / PLAGUE_BURST are one-shot: is_used=True after activation.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.mutation import Mutation, MutationRarity, MutationType
from bot.models.virus import Virus, VirusBranch, VirusUpgrade

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MUTATION_CONFIG: dict[MutationType, dict] = {
    # COMMON
    MutationType.TOXIC_SPIKE: {
        "rarity": MutationRarity.COMMON,
        "effect": 0.30,
        "duration": 6.0,
        "description": "+30% урона",
    },
    MutationType.UNSTABLE_CODE: {
        "rarity": MutationRarity.COMMON,
        "effect": -0.20,
        "duration": 4.0,
        "description": "-20% атаки",
    },
    MutationType.SLOW_REPLICATION: {
        "rarity": MutationRarity.COMMON,
        "effect": -0.30,
        "duration": 4.0,
        "description": "-30% заразности",
    },
    MutationType.IMMUNE_LEAK: {
        "rarity": MutationRarity.COMMON,
        "effect": -0.15,
        "duration": 6.0,
        "description": "-15% защиты",
    },
    # UNCOMMON
    MutationType.RAPID_SPREAD: {
        "rarity": MutationRarity.UNCOMMON,
        "effect": 0.50,
        "duration": 4.0,
        "description": "+50% заразности",
    },
    MutationType.REGENERATIVE_CORE: {
        "rarity": MutationRarity.UNCOMMON,
        "effect": 0.30,
        "duration": 6.0,
        "description": "+30% регенерации",
    },
    MutationType.BIO_MAGNET: {
        "rarity": MutationRarity.UNCOMMON,
        "effect": 1.00,
        "duration": 2.0,
        "description": "+100% к добыче ресурсов",
    },
    # RARE
    MutationType.PHANTOM_STRAIN: {
        "rarity": MutationRarity.RARE,
        "effect": 0.40,
        "duration": 8.0,
        "description": "+40% скрытности",
    },
    MutationType.RESOURCE_DRAIN: {
        "rarity": MutationRarity.RARE,
        "effect": 0.20,
        "duration": 6.0,
        "description": "+20% кражи ресурсов",
    },
    MutationType.ADAPTIVE_SHELL: {
        "rarity": MutationRarity.RARE,
        "effect": 0.25,
        "duration": 4.0,
        "description": "+25% ко всей защите",
    },
    MutationType.DOUBLE_STRIKE: {
        "rarity": MutationRarity.RARE,
        "effect": 0.0,
        "duration": 0.0,  # одноразово — не истекает по времени
        "description": "Две атаки вместо одной (одноразово)",
    },
    # LEGENDARY
    MutationType.PLAGUE_BURST: {
        "rarity": MutationRarity.LEGENDARY,
        "effect": 0.0,
        "duration": 0.0,  # одноразово
        "description": "Атака задевает 3 случайных игроков",
    },
    MutationType.ABSOLUTE_IMMUNITY: {
        "rarity": MutationRarity.LEGENDARY,
        "effect": 1.0,
        "duration": 1.0,
        "description": "Полная неуязвимость на 1 час",
    },
    MutationType.EVOLUTION_LEAP: {
        "rarity": MutationRarity.LEGENDARY,
        "effect": 1.0,
        "duration": 0.0,  # перманентно
        "description": "+1 уровень ко всем веткам вируса навсегда",
    },
}

RARITY_WEIGHTS: dict[MutationRarity, int] = {
    MutationRarity.COMMON: 60,
    MutationRarity.UNCOMMON: 25,
    MutationRarity.RARE: 12,
    MutationRarity.LEGENDARY: 3,
}

# Шанс получить мутацию при каждой атаке (15%)
MUTATION_ROLL_CHANCE: float = 0.15

# Типы мутаций, сгруппированные по редкости (вычисляется один раз)
_TYPES_BY_RARITY: dict[MutationRarity, list[MutationType]] = {
    rarity: [mt for mt, cfg in MUTATION_CONFIG.items() if cfg["rarity"] == rarity]
    for rarity in MutationRarity
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _is_expired(mutation: Mutation, now: datetime) -> bool:
    """Return True if mutation has a finite duration and that duration has elapsed."""
    if mutation.duration_hours == 0.0:
        return False  # перманентная или одноразовая — не истекает
    expiry = mutation.activated_at + timedelta(hours=mutation.duration_hours)
    return now >= expiry


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def roll_mutation(session: AsyncSession, user_id: int) -> Mutation | None:
    """
    Try to roll a mutation for *user_id* (15% chance).

    Returns the newly created and flushed Mutation, or None if no mutation occurred.
    EVOLUTION_LEAP is applied immediately if rolled.
    """
    if random.random() >= MUTATION_ROLL_CHANCE:
        return None

    # Выбираем редкость по весам
    rarities = list(RARITY_WEIGHTS.keys())
    weights = [RARITY_WEIGHTS[r] for r in rarities]
    chosen_rarity: MutationRarity = random.choices(rarities, weights=weights, k=1)[0]

    # Выбираем случайный тип из этой редкости
    candidates = _TYPES_BY_RARITY.get(chosen_rarity, [])
    if not candidates:
        return None
    chosen_type: MutationType = random.choice(candidates)

    cfg = MUTATION_CONFIG[chosen_type]
    mutation = Mutation(
        owner_id=user_id,
        mutation_type=chosen_type,
        rarity=chosen_rarity,
        effect_value=cfg["effect"],
        duration_hours=cfg["duration"],
        activated_at=_now_utc(),
        is_active=True,
        is_used=False,
    )
    session.add(mutation)
    await session.flush()

    # Немедленно применяем EVOLUTION_LEAP
    if chosen_type == MutationType.EVOLUTION_LEAP:
        await apply_evolution_leap(session, user_id)
        mutation.is_active = False  # помечаем как использованную сразу
        mutation.is_used = True
        await session.flush()

    return mutation


async def get_active_mutations(session: AsyncSession, user_id: int) -> list[Mutation]:
    """Return all currently active (not expired, not used) mutations of *user_id*."""
    result = await session.execute(
        select(Mutation).where(
            and_(
                Mutation.owner_id == user_id,
                Mutation.is_active == True,  # noqa: E712
                Mutation.is_used == False,   # noqa: E712
            )
        ).order_by(Mutation.activated_at.desc())
    )
    mutations = list(result.scalars().all())

    # Отфильтровываем истёкшие в памяти (без лишнего запроса)
    now = _now_utc()
    active: list[Mutation] = []
    for m in mutations:
        if _is_expired(m, now):
            m.is_active = False
        else:
            active.append(m)

    return active


async def get_mutation_bonus(
    session: AsyncSession, user_id: int, bonus_type: str
) -> float:
    """
    Return the cumulative multiplier bonus from all active mutations for *user_id*.

    bonus_type values:
      "attack"   — TOXIC_SPIKE, UNSTABLE_CODE
      "spread"   — RAPID_SPREAD, SLOW_REPLICATION
      "stealth"  — PHANTOM_STRAIN
      "defense"  — ADAPTIVE_SHELL, IMMUNE_LEAK, ABSOLUTE_IMMUNITY
      "regen"    — REGENERATIVE_CORE
      "mining"   — BIO_MAGNET, RESOURCE_DRAIN
    """
    _BONUS_MAP: dict[str, list[MutationType]] = {
        "attack":  [MutationType.TOXIC_SPIKE, MutationType.UNSTABLE_CODE],
        "spread":  [MutationType.RAPID_SPREAD, MutationType.SLOW_REPLICATION],
        "stealth": [MutationType.PHANTOM_STRAIN],
        "defense": [MutationType.ADAPTIVE_SHELL, MutationType.IMMUNE_LEAK, MutationType.ABSOLUTE_IMMUNITY],
        "regen":   [MutationType.REGENERATIVE_CORE],
        "mining":  [MutationType.BIO_MAGNET, MutationType.RESOURCE_DRAIN],
    }

    relevant_types = _BONUS_MAP.get(bonus_type, [])
    if not relevant_types:
        return 0.0

    active = await get_active_mutations(session, user_id)
    total_bonus: float = 0.0
    for m in active:
        if m.mutation_type in relevant_types:
            total_bonus += m.effect_value

    return total_bonus


async def expire_mutations(session: AsyncSession) -> int:
    """
    Deactivate all expired (by duration) active mutations across all users.

    Returns the number of mutations deactivated.
    """
    result = await session.execute(
        select(Mutation).where(
            and_(
                Mutation.is_active == True,  # noqa: E712
                Mutation.is_used == False,   # noqa: E712
                Mutation.duration_hours > 0.0,
            )
        )
    )
    candidates = list(result.scalars().all())

    now = _now_utc()
    count = 0
    for m in candidates:
        if _is_expired(m, now):
            m.is_active = False
            count += 1

    if count:
        await session.flush()

    return count


async def apply_evolution_leap(session: AsyncSession, user_id: int) -> None:
    """
    EVOLUTION_LEAP effect: +1 level to every virus upgrade branch owned by *user_id*.

    If the virus has no upgrade row for a branch yet, one is created at level 1.
    """
    result = await session.execute(
        select(Virus).where(Virus.owner_id == user_id)
    )
    virus = result.scalar_one_or_none()
    if virus is None:
        return

    upgrades_result = await session.execute(
        select(VirusUpgrade).where(VirusUpgrade.virus_id == virus.id)
    )
    existing: dict[VirusBranch, VirusUpgrade] = {
        u.branch: u for u in upgrades_result.scalars().all()
    }

    for branch in VirusBranch:
        if branch in existing:
            existing[branch].level += 1
        else:
            new_upg = VirusUpgrade(
                virus_id=virus.id,
                branch=branch,
                level=1,
                effect_value=0.0,
            )
            session.add(new_upg)

    await session.flush()


async def use_double_strike(session: AsyncSession, mutation_id: int) -> bool:
    """
    Mark a DOUBLE_STRIKE (or PLAGUE_BURST) mutation as used.

    Returns True on success, False if mutation not found or already used.
    """
    result = await session.execute(
        select(Mutation).where(
            and_(
                Mutation.id == mutation_id,
                Mutation.is_active == True,  # noqa: E712
                Mutation.is_used == False,   # noqa: E712
            )
        ).with_for_update()
    )
    mutation = result.scalar_one_or_none()
    if mutation is None:
        return False

    mutation.is_used = True
    mutation.is_active = False
    await session.flush()
    return True
