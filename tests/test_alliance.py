"""
Unit tests for bot/services/alliance.py
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.user import User
from bot.services.alliance import (
    create_alliance,
    get_alliance_defense_bonus,
    invite_player,
    kick_member,
    leave_alliance,
)
from bot.services.player import create_player


async def _give_coins(session: AsyncSession, tg_id: int, amount: int) -> None:
    """Helper: set bio_coins for a player."""
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = result.scalar_one()
    user.bio_coins = amount
    await session.flush()


async def test_create_alliance(session: AsyncSession):
    """A player with enough coins can create an alliance."""
    await create_player(session, tg_id=6001, username="leader1")
    await _give_coins(session, 6001, 1000)

    ok, msg = await create_alliance(session, leader_id=6001, name="Alpha Team", tag="ALPH")
    assert ok is True
    assert "ALPH" in msg
    assert "Alpha Team" in msg


async def test_create_alliance_not_enough_coins(session: AsyncSession):
    """Creating an alliance without enough coins fails."""
    await create_player(session, tg_id=6002, username="poorleader")
    # Leave bio_coins at 0

    ok, msg = await create_alliance(session, leader_id=6002, name="Beta Squad", tag="BETA")
    assert ok is False
    assert "Недостаточно" in msg


async def test_create_alliance_duplicate_name(session: AsyncSession):
    """Creating an alliance with a duplicate name fails."""
    await create_player(session, tg_id=6003, username="leader3")
    await _give_coins(session, 6003, 2000)

    ok1, _ = await create_alliance(session, leader_id=6003, name="Gamma Force", tag="GAMM")
    assert ok1 is True

    await create_player(session, tg_id=6004, username="leader4")
    await _give_coins(session, 6004, 2000)
    ok2, msg = await create_alliance(session, leader_id=6004, name="Gamma Force", tag="GMMX")
    assert ok2 is False
    assert "уже существует" in msg


async def test_invite_player(session: AsyncSession):
    """A leader can invite a player to the alliance."""
    await create_player(session, tg_id=6010, username="leader10")
    await create_player(session, tg_id=6011, username="member11")
    await _give_coins(session, 6010, 1000)

    await create_alliance(session, leader_id=6010, name="Delta Force", tag="DELT")

    ok, msg = await invite_player(session, inviter_id=6010, target_username="member11")
    assert ok is True
    assert "member11" in msg


async def test_invite_player_not_in_alliance(session: AsyncSession):
    """Inviting when the inviter is not in any alliance fails."""
    await create_player(session, tg_id=6020, username="loner20")
    await create_player(session, tg_id=6021, username="target21")

    ok, msg = await invite_player(session, inviter_id=6020, target_username="target21")
    assert ok is False
    assert "не состоишь" in msg


async def test_kick_member(session: AsyncSession):
    """Leader can kick a member from the alliance."""
    await create_player(session, tg_id=6030, username="leader30")
    await create_player(session, tg_id=6031, username="member31")
    await _give_coins(session, 6030, 1000)

    await create_alliance(session, leader_id=6030, name="Echo Unit", tag="ECHO")
    await invite_player(session, inviter_id=6030, target_username="member31")

    ok, msg = await kick_member(session, kicker_id=6030, target_id=6031)
    assert ok is True
    assert "member31" in msg


async def test_kick_self(session: AsyncSession):
    """Trying to kick yourself fails."""
    await create_player(session, tg_id=6040, username="leader40")
    await _give_coins(session, 6040, 1000)
    await create_alliance(session, leader_id=6040, name="Foxtrot", tag="FOXT")

    ok, msg = await kick_member(session, kicker_id=6040, target_id=6040)
    assert ok is False
    assert "самого себя" in msg


async def test_leave_alliance_member(session: AsyncSession):
    """A regular member can leave the alliance."""
    await create_player(session, tg_id=6050, username="leader50")
    await create_player(session, tg_id=6051, username="member51")
    await _give_coins(session, 6050, 1000)

    await create_alliance(session, leader_id=6050, name="Golf Club", tag="GOLF")
    await invite_player(session, inviter_id=6050, target_username="member51")

    ok, msg = await leave_alliance(session, user_id=6051)
    assert ok is True
    assert "Golf Club" in msg


async def test_leave_alliance_leader_dissolves(session: AsyncSession):
    """Leader leaving dissolves the alliance."""
    await create_player(session, tg_id=6060, username="leader60")
    await _give_coins(session, 6060, 1000)
    await create_alliance(session, leader_id=6060, name="Hotel Group", tag="HTLG")

    ok, msg = await leave_alliance(session, user_id=6060)
    assert ok is True
    # Should mention dissolution
    assert "распущен" in msg or "покинул" in msg


async def test_defense_bonus_single_member(session: AsyncSession):
    """Defense bonus is shield_level * effect_per_level (0 when freshly created)."""
    await create_player(session, tg_id=6070, username="leader70")
    await _give_coins(session, 6070, 1000)
    await create_alliance(session, leader_id=6070, name="India Squad", tag="INDI")

    bonus = await get_alliance_defense_bonus(session, user_id=6070)
    # New alliance has shield_level=0 → bonus = 0.0
    assert bonus == 0.0


async def test_defense_bonus_no_alliance(session: AsyncSession):
    """Player not in any alliance gets 0.0 defense bonus."""
    await create_player(session, tg_id=6080, username="nomad80")
    bonus = await get_alliance_defense_bonus(session, user_id=6080)
    assert bonus == 0.0
