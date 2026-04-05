"""
Unit tests for bot/services/player.py
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models.immunity import Immunity, ImmunityBranch, ImmunityUpgrade
from bot.models.user import User
from bot.models.virus import Virus, VirusBranch, VirusUpgrade
from bot.services.player import (
    DEFAULT_IMMUNITY_LEVEL,
    DEFAULT_VIRUS_LEVEL,
    DEFAULT_VIRUS_NAME,
    create_player,
    get_or_create_player,
    get_player_profile,
)


async def test_create_player(session: AsyncSession):
    """Creating a player produces User, Virus, Immunity and all branch upgrades."""
    user = await create_player(session, tg_id=1001, username="alice")

    assert user.tg_id == 1001
    assert user.username == "alice"
    assert user.bio_coins == 500  # new players start with 500 🧫 BioCoins
    assert user.premium_coins == 0

    # Virus exists with defaults
    virus_result = await session.execute(select(Virus).where(Virus.owner_id == 1001))
    virus = virus_result.scalar_one_or_none()
    assert virus is not None
    assert virus.name == DEFAULT_VIRUS_NAME
    assert virus.level == DEFAULT_VIRUS_LEVEL

    # All 3 virus upgrade branches created
    v_upgrades_result = await session.execute(
        select(VirusUpgrade).where(VirusUpgrade.virus_id == virus.id)
    )
    v_upgrades = v_upgrades_result.scalars().all()
    assert len(v_upgrades) == len(VirusBranch)
    upgrade_branches = {u.branch for u in v_upgrades}
    assert upgrade_branches == set(VirusBranch)
    for u in v_upgrades:
        assert u.level == 0
        assert u.effect_value == 0.0

    # Immunity exists with defaults
    imm_result = await session.execute(select(Immunity).where(Immunity.owner_id == 1001))
    immunity = imm_result.scalar_one_or_none()
    assert immunity is not None
    assert immunity.level == DEFAULT_IMMUNITY_LEVEL

    # All 3 immunity upgrade branches created
    i_upgrades_result = await session.execute(
        select(ImmunityUpgrade).where(ImmunityUpgrade.immunity_id == immunity.id)
    )
    i_upgrades = i_upgrades_result.scalars().all()
    assert len(i_upgrades) == len(ImmunityBranch)
    imm_upgrade_branches = {u.branch for u in i_upgrades}
    assert imm_upgrade_branches == set(ImmunityBranch)
    for u in i_upgrades:
        assert u.level == 0
        assert u.effect_value == 0.0


async def test_get_or_create_player_creates_new(session: AsyncSession):
    """get_or_create_player creates a new user when one does not exist."""
    user, is_new = await get_or_create_player(session, tg_id=1002, username="bob")
    assert user.tg_id == 1002
    assert user.username == "bob"
    assert is_new is True


async def test_get_or_create_player_returns_existing(session: AsyncSession):
    """get_or_create_player returns the same user on repeated calls."""
    await create_player(session, tg_id=1003, username="carol")
    user_a, _ = await get_or_create_player(session, tg_id=1003, username="carol")
    user_b, _ = await get_or_create_player(session, tg_id=1003, username="carol")
    assert user_a.tg_id == user_b.tg_id == 1003


async def test_get_or_create_player_updates_username(session: AsyncSession):
    """get_or_create_player syncs username when it changes."""
    await create_player(session, tg_id=1004, username="dave_old")
    user, _ = await get_or_create_player(session, tg_id=1004, username="dave_new")
    assert user.username == "dave_new"


async def test_get_player_profile(session: AsyncSession):
    """get_player_profile returns a correctly structured dict."""
    await create_player(session, tg_id=1005, username="eve")
    profile = await get_player_profile(session, user_id=1005)

    # Top-level keys
    assert "error" not in profile
    assert "user" in profile
    assert "virus" in profile
    assert "immunity" in profile
    assert "infections_sent_count" in profile
    assert "infections_received_count" in profile

    # User section
    u = profile["user"]
    assert u["tg_id"] == 1005
    assert u["username"] == "eve"
    assert u["bio_coins"] == 500  # new players start with 500 🧫 BioCoins
    assert u["premium_coins"] == 0

    # Virus section
    v = profile["virus"]
    assert v["name"] == DEFAULT_VIRUS_NAME
    assert v["level"] == DEFAULT_VIRUS_LEVEL
    assert "upgrades" in v
    assert len(v["upgrades"]) == len(VirusBranch)

    # Immunity section
    im = profile["immunity"]
    assert im["level"] == DEFAULT_IMMUNITY_LEVEL
    assert "upgrades" in im
    assert len(im["upgrades"]) == len(ImmunityBranch)

    # Infection counts start at zero
    assert profile["infections_sent_count"] == 0
    assert profile["infections_received_count"] == 0


async def test_get_player_profile_not_found(session: AsyncSession):
    """get_player_profile returns error dict for unknown user."""
    profile = await get_player_profile(session, user_id=999999)
    assert "error" in profile
