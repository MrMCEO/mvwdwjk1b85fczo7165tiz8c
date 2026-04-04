"""
Unit tests for display_name and format_username in bot/services/premium.py
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.user import User
from bot.services.player import create_player
from bot.services.premium import (
    DISPLAY_NAME_MAX_CHARS,
    clear_display_name,
    format_username,
    set_display_name,
)


# ---------------------------------------------------------------------------
# test_set_display_name
# ---------------------------------------------------------------------------


async def test_set_display_name(session: AsyncSession):
    """set_display_name persists the name on the user record."""
    await create_player(session, tg_id=5001, username="dn_user1")

    success, msg = await set_display_name(session, user_id=5001, name="BioKing")

    assert success is True
    assert "BioKing" in msg

    result = await session.execute(select(User).where(User.tg_id == 5001))
    user = result.scalar_one()
    assert user.display_name == "BioKing"


async def test_set_display_name_too_long(session: AsyncSession):
    """set_display_name rejects names that exceed the character limit."""
    await create_player(session, tg_id=5002, username="dn_user2")

    long_name = "A" * (DISPLAY_NAME_MAX_CHARS + 1)
    success, msg = await set_display_name(session, user_id=5002, name=long_name)

    assert success is False
    assert "длинн" in msg.lower() or "Максимум" in msg


async def test_set_display_name_empty(session: AsyncSession):
    """set_display_name rejects empty or whitespace-only names."""
    await create_player(session, tg_id=5003, username="dn_user3")

    success, msg = await set_display_name(session, user_id=5003, name="   ")

    assert success is False
    assert "пустым" in msg.lower() or "❌" in msg


# ---------------------------------------------------------------------------
# test_clear_display_name
# ---------------------------------------------------------------------------


async def test_clear_display_name(session: AsyncSession):
    """clear_display_name resets the display_name field to None."""
    await create_player(session, tg_id=5010, username="dn_clear")

    await set_display_name(session, user_id=5010, name="TempName")

    success, msg = await clear_display_name(session, user_id=5010)

    assert success is True

    result = await session.execute(select(User).where(User.tg_id == 5010))
    user = result.scalar_one()
    assert user.display_name is None


async def test_clear_display_name_not_set(session: AsyncSession):
    """clear_display_name succeeds even when no display_name was previously set."""
    await create_player(session, tg_id=5011, username="dn_clear2")

    success, msg = await clear_display_name(session, user_id=5011)

    assert success is True
    assert "сброш" in msg.lower() or "✅" in msg


# ---------------------------------------------------------------------------
# test_format_username_with_display_name
# ---------------------------------------------------------------------------


async def test_format_username_with_display_name(session: AsyncSession):
    """format_username uses display_name instead of base_username when provided."""
    result = format_username(
        base_username="regular_user",
        display_name="BioLord",
    )

    assert result == "BioLord"
    assert "regular_user" not in result


async def test_format_username_without_display_name(session: AsyncSession):
    """format_username falls back to base_username when display_name is None."""
    result = format_username(
        base_username="regular_user",
        display_name=None,
    )

    assert "regular_user" in result


async def test_format_username_with_status_emoji(session: AsyncSession):
    """format_username appends the status emoji when no prefix is set."""
    result = format_username(
        base_username="player1",
        display_name=None,
        status_emoji="🔵",
    )

    assert "player1" in result
    assert "🔵" in result


async def test_format_username_with_prefix_and_status(session: AsyncSession):
    """format_username prepends [PREFIX] when both prefix and status are present."""
    result = format_username(
        base_username="player2",
        display_name=None,
        prefix="VIP",
        is_premium_active=True,
    )

    assert "[VIP]" in result
    assert "player2" in result
