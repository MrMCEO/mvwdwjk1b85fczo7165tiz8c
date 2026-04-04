"""
Mutation effects helpers — compute per-action multipliers from active mutations.

These functions are called by combat/resource handlers (NOT by combat.py directly).
They return plain dicts/floats that handlers can pass into their own calculations.

Integration example in a future attack handler:
    bonuses = await apply_mutation_to_attack(session, attacker_id)
    effective_attack *= bonuses["attack_mult"]
    if bonuses["double_strike"]:
        # perform two attacks
        ...
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.mutation import MutationType
from bot.services.mutation import get_active_mutations, get_mutation_bonus


async def apply_mutation_to_attack(
    session: AsyncSession,
    attacker_id: int,
) -> dict:
    """
    Compute attack-phase multipliers from active mutations.

    Returns:
        {
            "attack_mult":  float,   # e.g. 1.30 means +30% damage
            "spread_mult":  float,   # e.g. 1.50 means +50% spread chance
            "stealth_mult": float,   # e.g. 1.40 means +40% stealth
            "double_strike": bool,   # True if unused DOUBLE_STRIKE is present
            "plague_burst":  bool,   # True if unused PLAGUE_BURST is present
        }
    """
    attack_bonus = await get_mutation_bonus(session, attacker_id, "attack")
    spread_bonus = await get_mutation_bonus(session, attacker_id, "spread")
    stealth_bonus = await get_mutation_bonus(session, attacker_id, "stealth")

    # Check one-shot mutations
    active = await get_active_mutations(session, attacker_id)
    has_double_strike = any(
        m.mutation_type == MutationType.DOUBLE_STRIKE
        and not m.is_used
        for m in active
    )
    has_plague_burst = any(
        m.mutation_type == MutationType.PLAGUE_BURST
        and not m.is_used
        for m in active
    )

    return {
        "attack_mult":   1.0 + attack_bonus,
        "spread_mult":   1.0 + spread_bonus,
        "stealth_mult":  1.0 + stealth_bonus,
        "double_strike": has_double_strike,
        "plague_burst":  has_plague_burst,
    }


async def apply_mutation_to_defense(
    session: AsyncSession,
    defender_id: int,
) -> dict:
    """
    Compute defense-phase multipliers from active mutations.

    Returns:
        {
            "defense_mult": float,   # e.g. 1.25 means +25% defense
            "regen_mult":   float,   # e.g. 1.30 means +30% regen
            "absolute_immunity": bool,  # True if ABSOLUTE_IMMUNITY is active
        }
    """
    defense_bonus = await get_mutation_bonus(session, defender_id, "defense")
    regen_bonus = await get_mutation_bonus(session, defender_id, "regen")

    active = await get_active_mutations(session, defender_id)
    has_absolute = any(
        m.mutation_type == MutationType.ABSOLUTE_IMMUNITY
        for m in active
    )

    return {
        "defense_mult":      1.0 + defense_bonus,
        "regen_mult":        1.0 + regen_bonus,
        "absolute_immunity": has_absolute,
    }


async def apply_mutation_to_mining(
    session: AsyncSession,
    user_id: int,
) -> float:
    """
    Return the mining multiplier from active mutations (e.g. 2.0 means ×2 loot).

    BIO_MAGNET adds +100% (effect_value=1.0), RESOURCE_DRAIN adds +20% to mining.
    """
    mining_bonus = await get_mutation_bonus(session, user_id, "mining")
    return 1.0 + mining_bonus
