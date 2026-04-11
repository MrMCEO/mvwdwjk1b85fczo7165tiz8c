"""
Unit tests for bot/services/upgrade.py
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.virus import VirusUpgrade, VirusBranch
from bot.models.immunity import ImmunityUpgrade, ImmunityBranch
from bot.services.player import create_player
from bot.services.upgrade import (
    UPGRADE_CONFIG,
    calc_upgrade_cost,
    get_immunity_stats,
    get_virus_stats,
    upgrade_immunity_branch,
    upgrade_virus_branch,
)


# ---------------------------------------------------------------------------
# Pure formula tests (no DB needed)
# ---------------------------------------------------------------------------


def test_upgrade_cost_formula_level0():
    """Buying level 1 costs exactly base_cost."""
    assert calc_upgrade_cost(100, 1.5, 0) == 100


def test_upgrade_cost_formula_level1():
    """Buying level 2 costs base_cost * multiplier."""
    assert calc_upgrade_cost(100, 1.5, 1) == 150


def test_upgrade_cost_formula_level3():
    """Buying level 4 matches int(100 * 1.5**3) = 337."""
    assert calc_upgrade_cost(100, 1.5, 3) == 337


# ---------------------------------------------------------------------------
# Virus branch upgrade tests
# ---------------------------------------------------------------------------


async def test_upgrade_virus_branch(session: AsyncSession):
    """Successful virus branch upgrade deducts coins and increases level."""
    await create_player(session, tg_id=3001, username="vupgrade1")

    # Give enough coins
    from bot.models.user import User
    result = await session.execute(select(User).where(User.tg_id == 3001))
    user = result.scalar_one()
    user.bio_coins = 10_000
    await session.flush()

    success, msg, stats = await upgrade_virus_branch(session, user_id=3001, branch="LETHALITY")

    assert success is True
    assert "прокачана до уровня 1" in msg
    assert stats is not None
    assert "upgrades" in stats

    # Verify upgrade row in DB
    from sqlalchemy import select as sa_select
    from bot.models.virus import Virus
    virus_res = await session.execute(sa_select(Virus).where(Virus.owner_id == 3001))
    virus = virus_res.scalar_one()

    upgrade_res = await session.execute(
        sa_select(VirusUpgrade).where(
            VirusUpgrade.virus_id == virus.id,
            VirusUpgrade.branch == VirusBranch.LETHALITY,
        )
    )
    upgrade = upgrade_res.scalar_one()
    assert upgrade.level == 1
    assert upgrade.effect_value > 0


async def test_upgrade_not_enough_coins(session: AsyncSession):
    """Upgrade fails when player has insufficient bio_coins."""
    await create_player(session, tg_id=3002, username="poor1")

    # Drain coins to 0 so player can't afford the upgrade
    from bot.models.user import User
    result = await session.execute(select(User).where(User.tg_id == 3002))
    user = result.scalar_one()
    user.bio_coins = 0
    await session.flush()

    success, msg, stats = await upgrade_virus_branch(session, user_id=3002, branch="LETHALITY")

    assert success is False
    assert "Недостаточно" in msg
    assert stats is None


async def test_upgrade_cost_deducted_correctly(session: AsyncSession):
    """Exact cost is deducted from bio_coins on a successful upgrade."""
    await create_player(session, tg_id=3003, username="cost1")

    from bot.models.user import User
    result = await session.execute(select(User).where(User.tg_id == 3003))
    user = result.scalar_one()
    user.bio_coins = 500
    await session.flush()

    cfg = UPGRADE_CONFIG["virus"]["LETHALITY"]
    expected_cost = calc_upgrade_cost(cfg["base_cost"], cfg["multiplier"], 0)

    await upgrade_virus_branch(session, user_id=3003, branch="LETHALITY")

    result2 = await session.execute(select(User).where(User.tg_id == 3003))
    user2 = result2.scalar_one()
    assert user2.bio_coins == 500 - expected_cost


async def test_upgrade_immunity_branch(session: AsyncSession):
    """Successful immunity branch upgrade deducts coins and increases level."""
    await create_player(session, tg_id=3010, username="iupgrade1")

    from bot.models.user import User
    result = await session.execute(select(User).where(User.tg_id == 3010))
    user = result.scalar_one()
    user.bio_coins = 10_000
    await session.flush()

    success, msg, stats = await upgrade_immunity_branch(session, user_id=3010, branch="BARRIER")

    assert success is True
    assert "прокачана до уровня 1" in msg
    assert stats is not None
    assert "upgrades" in stats

    from bot.models.immunity import Immunity
    imm_res = await session.execute(select(Immunity).where(Immunity.owner_id == 3010))
    immunity = imm_res.scalar_one()

    upg_res = await session.execute(
        select(ImmunityUpgrade).where(
            ImmunityUpgrade.immunity_id == immunity.id,
            ImmunityUpgrade.branch == ImmunityBranch.BARRIER,
        )
    )
    upgrade = upg_res.scalar_one()
    assert upgrade.level == 1
    assert upgrade.effect_value > 0


async def test_upgrade_immunity_not_enough_coins(session: AsyncSession):
    """Immunity upgrade fails with no coins."""
    await create_player(session, tg_id=3011, username="poor_imm")

    # Drain coins to 0 so player can't afford the upgrade
    from bot.models.user import User
    result = await session.execute(select(User).where(User.tg_id == 3011))
    user = result.scalar_one()
    user.bio_coins = 0
    await session.flush()

    success, msg, stats = await upgrade_immunity_branch(session, user_id=3011, branch="BARRIER")
    assert success is False
    assert "Недostаточно" in msg or "Недостаточно" in msg
    assert stats is None


async def test_get_virus_stats(session: AsyncSession):
    """get_virus_stats returns correctly structured dict."""
    await create_player(session, tg_id=3020, username="vstats1")
    stats = await get_virus_stats(session, user_id=3020)

    assert "error" not in stats
    assert "virus" in stats
    assert "upgrades" in stats

    v = stats["virus"]
    assert "id" in v
    assert "name" in v
    assert "level" in v

    upgrades = stats["upgrades"]
    # All 3 branches present
    assert set(upgrades.keys()) == {"LETHALITY", "CONTAGION", "STEALTH"}
    for key, data in upgrades.items():
        assert "level" in data
        assert "effect_value" in data
        assert "next_cost" in data
        assert data["level"] == 0  # fresh player


async def test_get_immunity_stats(session: AsyncSession):
    """get_immunity_stats returns correctly structured dict."""
    await create_player(session, tg_id=3030, username="istats1")
    stats = await get_immunity_stats(session, user_id=3030)

    assert "error" not in stats
    assert "immunity" in stats
    assert "upgrades" in stats

    im = stats["immunity"]
    assert "id" in im
    assert "level" in im
    assert "resistance" in im

    upgrades = stats["upgrades"]
    assert set(upgrades.keys()) == {"BARRIER", "DETECTION", "REGENERATION"}
    for key, data in upgrades.items():
        assert "level" in data
        assert "effect_value" in data
        assert "next_cost" in data
        assert data["level"] == 0


async def test_get_virus_stats_not_found(session: AsyncSession):
    """get_virus_stats returns error for unknown user."""
    stats = await get_virus_stats(session, user_id=999002)
    assert "error" in stats


async def test_get_immunity_stats_not_found(session: AsyncSession):
    """get_immunity_stats returns error for unknown user."""
    stats = await get_immunity_stats(session, user_id=999003)
    assert "error" in stats
