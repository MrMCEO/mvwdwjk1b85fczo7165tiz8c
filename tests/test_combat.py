"""
Unit tests for bot/services/combat.py
"""
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.infection import Infection
from bot.models.user import User
from bot.services.combat import (
    ATTACK_COOLDOWN,
    attack_player,
    get_active_infections_by,
    get_active_infections_on,
    try_cure,
)
from bot.services.player import create_player


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _give_coins(session: AsyncSession, tg_id: int, amount: int) -> None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = result.scalar_one()
    user.bio_coins = amount
    await session.flush()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_attack_player_success(session: AsyncSession):
    """Successful attack creates an active Infection row."""
    await create_player(session, tg_id=4001, username="attacker1")
    await create_player(session, tg_id=4002, username="victim1")

    # Force random to return a very low value → attack always wins
    with patch("bot.services.combat.random.random", return_value=0.0):
        success, msg = await attack_player(session, attacker_id=4001, victim_id=4002)

    assert success is True
    assert "заражён" in msg

    infections = await get_active_infections_by(session, user_id=4001)
    assert len(infections) == 1
    assert infections[0].victim_id == 4002
    assert infections[0].is_active is True


async def test_attack_self(session: AsyncSession):
    """Attacking yourself returns False."""
    await create_player(session, tg_id=4010, username="selfie")
    success, msg = await attack_player(session, attacker_id=4010, victim_id=4010)
    assert success is False
    assert "самого себя" in msg


async def test_attack_cooldown(session: AsyncSession):
    """Second attack within cooldown window returns False."""
    await create_player(session, tg_id=4020, username="cd_attacker")
    await create_player(session, tg_id=4021, username="cd_victim1")
    await create_player(session, tg_id=4022, username="cd_victim2")

    # First attack succeeds
    with patch("bot.services.combat.random.random", return_value=0.0):
        success1, _ = await attack_player(session, attacker_id=4020, victim_id=4021)
    assert success1 is True

    # Second attack immediately after should fail due to cooldown
    with patch("bot.services.combat.random.random", return_value=0.0):
        success2, msg2 = await attack_player(session, attacker_id=4020, victim_id=4022)
    assert success2 is False
    assert "Кулдаун" in msg2 or "не истёк" in msg2


async def test_attack_already_infected(session: AsyncSession):
    """Attacking a victim already infected by same attacker returns False."""
    await create_player(session, tg_id=4030, username="double_attacker")
    await create_player(session, tg_id=4031, username="double_victim")

    # Inject infection directly (bypassing cooldown)
    now_utc = datetime.now(UTC).replace(tzinfo=None)
    infection = Infection(
        attacker_id=4030,
        victim_id=4031,
        started_at=now_utc - ATTACK_COOLDOWN - timedelta(minutes=1),
        damage_per_tick=5.0,
        is_active=True,
    )
    session.add(infection)
    await session.flush()

    # Now try to attack the same victim again — should fail (already infected)
    with patch("bot.services.combat.random.random", return_value=0.0):
        success, msg = await attack_player(session, attacker_id=4030, victim_id=4031)

    assert success is False
    assert "уже заражён" in msg


async def test_attack_fails_on_high_roll(session: AsyncSession):
    """Attack fails when random roll is high (defense wins)."""
    await create_player(session, tg_id=4040, username="attacker_fail")
    await create_player(session, tg_id=4041, username="victim_fail")

    # Force random to return 1.0 → attack always fails
    with patch("bot.services.combat.random.random", return_value=1.0):
        success, msg = await attack_player(session, attacker_id=4040, victim_id=4041)

    assert success is False
    assert "провалилась" in msg


async def test_try_cure(session: AsyncSession):
    """Player can cure an active infection by spending bio_coins."""
    await create_player(session, tg_id=4050, username="curer1")
    await create_player(session, tg_id=4051, username="infected1")

    # Give the victim enough coins to cure
    await _give_coins(session, 4051, 1000)

    # Insert active infection directly
    now_utc = datetime.now(UTC).replace(tzinfo=None)
    infection = Infection(
        attacker_id=4050,
        victim_id=4051,
        started_at=now_utc,
        damage_per_tick=5.0,
        is_active=True,
    )
    session.add(infection)
    await session.flush()
    infection_id = infection.id

    success, msg = await try_cure(session, user_id=4051, infection_id=infection_id)

    assert success is True
    assert "вылечено" in msg

    # Infection is now inactive
    result = await session.execute(select(Infection).where(Infection.id == infection_id))
    refreshed = result.scalar_one()
    assert refreshed.is_active is False


async def test_try_cure_not_enough_coins(session: AsyncSession):
    """Cure fails if player doesn't have enough bio_coins."""
    await create_player(session, tg_id=4060, username="broker_curer")
    await create_player(session, tg_id=4061, username="broke_infected")
    # No coins for victim

    now_utc = datetime.now(UTC).replace(tzinfo=None)
    infection = Infection(
        attacker_id=4060,
        victim_id=4061,
        started_at=now_utc,
        damage_per_tick=5.0,
        is_active=True,
    )
    session.add(infection)
    await session.flush()

    success, msg = await try_cure(session, user_id=4061, infection_id=infection.id)
    assert success is False
    assert "Недостаточно" in msg


async def test_try_cure_wrong_owner(session: AsyncSession):
    """Cure fails if infection doesn't belong to the requesting player."""
    await create_player(session, tg_id=4070, username="thief_curer")
    await create_player(session, tg_id=4071, username="real_victim")
    await create_player(session, tg_id=4072, username="real_attacker")

    now_utc = datetime.now(UTC).replace(tzinfo=None)
    infection = Infection(
        attacker_id=4072,
        victim_id=4071,
        started_at=now_utc,
        damage_per_tick=5.0,
        is_active=True,
    )
    session.add(infection)
    await session.flush()

    # Player 4070 (not the victim) tries to cure
    success, msg = await try_cure(session, user_id=4070, infection_id=infection.id)
    assert success is False
    assert "не найдено" in msg


async def test_get_active_infections(session: AsyncSession):
    """get_active_infections_by and get_active_infections_on return correct lists."""
    await create_player(session, tg_id=4080, username="infector")
    await create_player(session, tg_id=4081, username="target1")
    await create_player(session, tg_id=4082, username="target2")

    now_utc = datetime.now(UTC).replace(tzinfo=None)
    inf1 = Infection(attacker_id=4080, victim_id=4081, started_at=now_utc, damage_per_tick=5.0, is_active=True)
    inf2 = Infection(attacker_id=4080, victim_id=4082, started_at=now_utc, damage_per_tick=5.0, is_active=True)
    session.add_all([inf1, inf2])
    await session.flush()

    sent = await get_active_infections_by(session, user_id=4080)
    assert len(sent) == 2

    received_81 = await get_active_infections_on(session, user_id=4081)
    assert len(received_81) == 1
    assert received_81[0].attacker_id == 4080

    received_82 = await get_active_infections_on(session, user_id=4082)
    assert len(received_82) == 1


async def test_get_active_infections_empty(session: AsyncSession):
    """Lists are empty for player with no infections."""
    await create_player(session, tg_id=4090, username="clean_player")

    sent = await get_active_infections_by(session, user_id=4090)
    received = await get_active_infections_on(session, user_id=4090)

    assert sent == []
    assert received == []
