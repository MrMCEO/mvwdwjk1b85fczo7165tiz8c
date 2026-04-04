"""
Unit tests for bot/services/mutation.py
"""
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.mutation import Mutation, MutationRarity, MutationType
from bot.services.mutation import (
    MUTATION_ROLL_CHANCE,
    expire_mutations,
    get_active_mutations,
    get_mutation_bonus,
    roll_mutation,
)
from bot.services.player import create_player


async def test_roll_mutation_returns_mutation_when_lucky(session: AsyncSession):
    """roll_mutation returns a Mutation when the random roll succeeds."""
    await create_player(session, tg_id=5001, username="mutant1")

    # Force the roll to succeed and pick TOXIC_SPIKE (COMMON)
    with patch("bot.services.mutation.random.random", return_value=0.0), \
         patch("bot.services.mutation.random.choices", return_value=[MutationRarity.COMMON]), \
         patch("bot.services.mutation.random.choice", return_value=MutationType.TOXIC_SPIKE):
        result = await roll_mutation(session, user_id=5001)

    assert result is not None
    assert isinstance(result, Mutation)
    assert result.owner_id == 5001
    assert result.is_active is True
    assert result.mutation_type == MutationType.TOXIC_SPIKE


async def test_roll_mutation_returns_none_when_unlucky(session: AsyncSession):
    """roll_mutation returns None when the random roll fails."""
    await create_player(session, tg_id=5002, username="mutant2")

    # Force the roll to fail (value >= MUTATION_ROLL_CHANCE)
    with patch("bot.services.mutation.random.random", return_value=1.0):
        result = await roll_mutation(session, user_id=5002)

    assert result is None


async def test_get_active_mutations_returns_active(session: AsyncSession):
    """get_active_mutations returns mutations that are active and not expired."""
    await create_player(session, tg_id=5003, username="mutant3")

    # Insert a valid active mutation manually
    now = datetime.now(UTC).replace(tzinfo=None)
    mutation = Mutation(
        owner_id=5003,
        mutation_type=MutationType.RAPID_SPREAD,
        rarity=MutationRarity.UNCOMMON,
        effect_value=0.50,
        duration_hours=4.0,
        activated_at=now,
        is_active=True,
        is_used=False,
    )
    session.add(mutation)
    await session.flush()

    active = await get_active_mutations(session, user_id=5003)
    assert len(active) == 1
    assert active[0].mutation_type == MutationType.RAPID_SPREAD


async def test_get_active_mutations_empty(session: AsyncSession):
    """get_active_mutations returns empty list for player with no mutations."""
    await create_player(session, tg_id=5004, username="mutant4")
    active = await get_active_mutations(session, user_id=5004)
    assert active == []


async def test_expire_mutations_deactivates_expired(session: AsyncSession):
    """expire_mutations deactivates mutations whose duration has elapsed."""
    await create_player(session, tg_id=5005, username="mutant5")

    # Insert a mutation that expired 2 hours ago
    now = datetime.now(UTC).replace(tzinfo=None)
    expired_mutation = Mutation(
        owner_id=5005,
        mutation_type=MutationType.TOXIC_SPIKE,
        rarity=MutationRarity.COMMON,
        effect_value=0.30,
        duration_hours=1.0,
        activated_at=now - timedelta(hours=2),
        is_active=True,
        is_used=False,
    )
    session.add(expired_mutation)
    await session.flush()

    deactivated = await expire_mutations(session)
    assert deactivated >= 1

    # Reload and check flag
    await session.refresh(expired_mutation)
    assert expired_mutation.is_active is False


async def test_expire_mutations_does_not_deactivate_permanent(session: AsyncSession):
    """expire_mutations does not deactivate permanent mutations (duration_hours=0)."""
    await create_player(session, tg_id=5006, username="mutant6")

    now = datetime.now(UTC).replace(tzinfo=None)
    permanent = Mutation(
        owner_id=5006,
        mutation_type=MutationType.DOUBLE_STRIKE,
        rarity=MutationRarity.RARE,
        effect_value=0.0,
        duration_hours=0.0,
        activated_at=now - timedelta(hours=100),
        is_active=True,
        is_used=False,
    )
    session.add(permanent)
    await session.flush()

    deactivated = await expire_mutations(session)

    await session.refresh(permanent)
    assert permanent.is_active is True


async def test_mutation_bonus_from_active_mutation(session: AsyncSession):
    """get_mutation_bonus sums effect_value from relevant active mutations."""
    await create_player(session, tg_id=5007, username="mutant7")

    now = datetime.now(UTC).replace(tzinfo=None)
    # Add a TOXIC_SPIKE which contributes to "attack" bonus
    mutation = Mutation(
        owner_id=5007,
        mutation_type=MutationType.TOXIC_SPIKE,
        rarity=MutationRarity.COMMON,
        effect_value=0.30,
        duration_hours=6.0,
        activated_at=now,
        is_active=True,
        is_used=False,
    )
    session.add(mutation)
    await session.flush()

    bonus = await get_mutation_bonus(session, user_id=5007, bonus_type="attack")
    assert abs(bonus - 0.30) < 1e-9


async def test_mutation_bonus_zero_for_wrong_type(session: AsyncSession):
    """get_mutation_bonus returns 0.0 when no relevant mutations exist."""
    await create_player(session, tg_id=5008, username="mutant8")

    now = datetime.now(UTC).replace(tzinfo=None)
    # Add a spread mutation but query for "attack"
    mutation = Mutation(
        owner_id=5008,
        mutation_type=MutationType.RAPID_SPREAD,
        rarity=MutationRarity.UNCOMMON,
        effect_value=0.50,
        duration_hours=4.0,
        activated_at=now,
        is_active=True,
        is_used=False,
    )
    session.add(mutation)
    await session.flush()

    bonus = await get_mutation_bonus(session, user_id=5008, bonus_type="attack")
    assert bonus == 0.0
