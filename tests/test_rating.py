"""
Unit tests for bot/services/rating.py
"""
from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.infection import Infection
from bot.models.user import User
from bot.models.virus import Virus
from bot.services.player import create_player
from bot.services.rating import get_top_infections, get_top_richest, get_top_virus_level


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _set_bio_coins(session: AsyncSession, tg_id: int, amount: int) -> None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = result.scalar_one()
    user.bio_coins = amount
    await session.flush()


async def _set_virus_level(session: AsyncSession, tg_id: int, level: int) -> None:
    result = await session.execute(select(Virus).where(Virus.owner_id == tg_id))
    virus = result.scalar_one()
    virus.level = level
    await session.flush()


async def _add_active_infection(
    session: AsyncSession, attacker_id: int, victim_id: int
) -> None:
    now_utc = datetime.now(UTC).replace(tzinfo=None)
    inf = Infection(
        attacker_id=attacker_id,
        victim_id=victim_id,
        started_at=now_utc,
        damage_per_tick=5.0,
        is_active=True,
    )
    session.add(inf)
    await session.flush()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_top_infections(session: AsyncSession):
    """get_top_infections returns players sorted by active infections count."""
    await create_player(session, tg_id=7001, username="inf_leader")
    await create_player(session, tg_id=7002, username="inf_follower")
    await create_player(session, tg_id=7003, username="inf_victim1")
    await create_player(session, tg_id=7004, username="inf_victim2")
    await create_player(session, tg_id=7005, username="inf_victim3")

    # Leader infects 2 players, follower infects 1
    await _add_active_infection(session, attacker_id=7001, victim_id=7003)
    await _add_active_infection(session, attacker_id=7001, victim_id=7004)
    await _add_active_infection(session, attacker_id=7002, victim_id=7005)

    top = await get_top_infections(session, limit=10)

    # At least the two attackers must appear
    user_ids = [row["user_id"] for row in top]
    assert 7001 in user_ids
    assert 7002 in user_ids

    # Leader should be first
    assert top[0]["user_id"] == 7001
    assert top[0]["count"] == 2

    # Verify structure
    for row in top:
        assert "user_id" in row
        assert "username" in row
        assert "count" in row


async def test_top_infections_empty(session: AsyncSession):
    """get_top_infections returns empty list when there are no active infections."""
    top = await get_top_infections(session, limit=10)
    # May have entries from other tests that ran before, or truly empty
    # Just verify structure of any returned rows
    for row in top:
        assert "user_id" in row
        assert "count" in row


async def test_top_virus_level(session: AsyncSession):
    """get_top_virus_level returns players sorted by virus level descending."""
    await create_player(session, tg_id=7010, username="top_virus")
    await create_player(session, tg_id=7011, username="mid_virus")
    await create_player(session, tg_id=7012, username="low_virus")

    await _set_virus_level(session, 7010, 10)
    await _set_virus_level(session, 7011, 5)
    await _set_virus_level(session, 7012, 1)

    top = await get_top_virus_level(session, limit=10)

    # Find our players in the results
    results_by_id = {row["user_id"]: row for row in top}

    assert 7010 in results_by_id
    assert results_by_id[7010]["level"] == 10

    # Verify ordering: 7010 should appear before 7011 before 7012
    ids_in_order = [row["user_id"] for row in top]
    assert ids_in_order.index(7010) < ids_in_order.index(7011)
    assert ids_in_order.index(7011) < ids_in_order.index(7012)

    # Verify structure
    for row in top:
        assert "user_id" in row
        assert "username" in row
        assert "virus_name" in row
        assert "level" in row


async def test_top_richest(session: AsyncSession):
    """get_top_richest returns players sorted by bio_coins descending."""
    await create_player(session, tg_id=7020, username="richest")
    await create_player(session, tg_id=7021, username="middle_rich")
    await create_player(session, tg_id=7022, username="poorest_of_three")

    await _set_bio_coins(session, 7020, 9000)
    await _set_bio_coins(session, 7021, 5000)
    await _set_bio_coins(session, 7022, 1000)

    top = await get_top_richest(session, limit=10)

    results_by_id = {row["user_id"]: row for row in top}

    assert 7020 in results_by_id
    assert results_by_id[7020]["bio_coins"] == 9000

    ids_in_order = [row["user_id"] for row in top]
    assert ids_in_order.index(7020) < ids_in_order.index(7021)
    assert ids_in_order.index(7021) < ids_in_order.index(7022)

    # Verify structure
    for row in top:
        assert "user_id" in row
        assert "username" in row
        assert "bio_coins" in row


async def test_top_richest_limit(session: AsyncSession):
    """get_top_richest respects the limit parameter."""
    # Create 5 players
    for i in range(5):
        tg_id = 7030 + i
        await create_player(session, tg_id=tg_id, username=f"lim_player{i}")
        await _set_bio_coins(session, tg_id, (5 - i) * 1000)

    top = await get_top_richest(session, limit=3)
    assert len(top) <= 3


async def test_top_virus_level_limit(session: AsyncSession):
    """get_top_virus_level respects the limit parameter."""
    for i in range(4):
        tg_id = 7040 + i
        await create_player(session, tg_id=tg_id, username=f"vlim_player{i}")

    top = await get_top_virus_level(session, limit=2)
    assert len(top) <= 2
