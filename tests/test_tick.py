"""
Unit tests for bot/services/tick.py
"""
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.infection import Infection
from bot.models.user import User
from bot.services.player import create_player
from bot.services.tick import ATTACKER_SHARE, BASE_CURE_CHANCE, process_infection_tick


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _give_coins(session: AsyncSession, tg_id: int, amount: int) -> None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = result.scalar_one()
    user.bio_coins = amount
    await session.flush()


async def _get_coins(session: AsyncSession, tg_id: int) -> int:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = result.scalar_one()
    return user.bio_coins


async def _create_infection(
    session: AsyncSession,
    attacker_id: int,
    victim_id: int,
    damage_per_tick: float = 10.0,
    is_active: bool = True,
) -> Infection:
    now_utc = datetime.now(UTC).replace(tzinfo=None)
    inf = Infection(
        attacker_id=attacker_id,
        victim_id=victim_id,
        started_at=now_utc,
        damage_per_tick=damage_per_tick,
        is_active=is_active,
    )
    session.add(inf)
    await session.flush()
    return inf


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_process_infection_tick(session: AsyncSession):
    """Tick drains bio_coins from victim and gives a share to attacker."""
    await create_player(session, tg_id=5001, username="tick_attacker")
    await create_player(session, tg_id=5002, username="tick_victim")

    await _give_coins(session, 5002, 100)
    damage = 20.0
    await _create_infection(session, attacker_id=5001, victim_id=5002, damage_per_tick=damage)

    # Prevent auto-cure during this tick
    # random is imported locally inside process_infection_tick, patch the stdlib
    with patch("random.random", return_value=1.0):
        notifications = await process_infection_tick(session)

    victim_coins = await _get_coins(session, 5002)
    attacker_coins = await _get_coins(session, 5001)

    expected_drain = int(damage)
    expected_attacker_gain = int(expected_drain * ATTACKER_SHARE)

    assert victim_coins == 100 - expected_drain
    assert attacker_coins == expected_attacker_gain
    # Notifications for both
    user_ids_notified = {n["user_id"] for n in notifications}
    assert 5001 in user_ids_notified
    assert 5002 in user_ids_notified


async def test_tick_auto_cure(session: AsyncSession):
    """Tick deactivates infection when auto-cure roll succeeds."""
    await create_player(session, tg_id=5010, username="ac_attacker")
    await create_player(session, tg_id=5011, username="ac_victim")

    await _give_coins(session, 5011, 100)
    inf = await _create_infection(
        session, attacker_id=5010, victim_id=5011, damage_per_tick=5.0
    )

    # Force auto-cure to succeed (random imported locally in tick, patch stdlib)
    with patch("random.random", return_value=0.0):
        notifications = await process_infection_tick(session)

    # Re-fetch infection
    result = await session.execute(select(Infection).where(Infection.id == inf.id))
    updated_inf = result.scalar_one()
    assert updated_inf.is_active is False

    # Notification about cure sent to victim
    cure_notes = [n for n in notifications if n["user_id"] == 5011 and "вылечено" in n["message"]]
    assert len(cure_notes) == 1


async def test_tick_no_negative_balance(session: AsyncSession):
    """Tick does not reduce victim's bio_coins below zero."""
    await create_player(session, tg_id=5020, username="broke_victim")
    await create_player(session, tg_id=5021, username="greedy_attacker")

    # Victim has only 3 coins but damage is 20
    await _give_coins(session, 5020, 3)
    await _create_infection(
        session, attacker_id=5021, victim_id=5020, damage_per_tick=20.0
    )

    # Prevent auto-cure (random imported locally in tick, patch stdlib)
    with patch("random.random", return_value=1.0):
        await process_infection_tick(session)

    victim_coins = await _get_coins(session, 5020)
    assert victim_coins >= 0


async def test_tick_no_active_infections(session: AsyncSession):
    """Tick with no active infections returns empty notifications list."""
    # Create two players but no infection
    await create_player(session, tg_id=5030, username="idle1")
    await create_player(session, tg_id=5031, username="idle2")

    notifications = await process_infection_tick(session)
    assert notifications == []


async def test_tick_inactive_infection_skipped(session: AsyncSession):
    """Tick skips infections that are already inactive."""
    await create_player(session, tg_id=5040, username="skip_attacker")
    await create_player(session, tg_id=5041, username="skip_victim")

    await _give_coins(session, 5041, 100)
    await _create_infection(
        session, attacker_id=5040, victim_id=5041, damage_per_tick=10.0, is_active=False
    )

    with patch("random.random", return_value=1.0):
        notifications = await process_infection_tick(session)

    # No coins should have been drained
    victim_coins = await _get_coins(session, 5041)
    assert victim_coins == 100
    assert notifications == []
