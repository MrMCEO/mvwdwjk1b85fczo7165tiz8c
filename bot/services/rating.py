"""
Rating service — leaderboard queries.

All functions return plain dicts — no ORM objects leak to handlers.
"""

from __future__ import annotations

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.immunity import Immunity
from bot.models.infection import Infection
from bot.models.user import User
from bot.models.virus import Virus


async def get_top_infections(session: AsyncSession, limit: int = 10) -> list[dict]:
    """
    Top players by number of ACTIVE outgoing infections.

    Returns list of {user_id, username, count, premium_until}.
    """
    stmt = (
        select(
            Infection.attacker_id.label("user_id"),
            User.username.label("username"),
            User.premium_until.label("premium_until"),
            func.count(Infection.id).label("count"),
        )
        .join(User, User.tg_id == Infection.attacker_id)
        .where(Infection.is_active == True)  # noqa: E712
        .group_by(Infection.attacker_id, User.username, User.premium_until)
        .order_by(desc("count"))
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.all()
    return [
        {
            "user_id": row.user_id,
            "username": row.username or str(row.user_id),
            "count": row.count,
            "premium_until": row.premium_until,
        }
        for row in rows
    ]


async def get_top_virus_level(session: AsyncSession, limit: int = 10) -> list[dict]:
    """
    Top players by virus level.

    Returns list of {user_id, username, virus_name, level, premium_until}.
    """
    stmt = (
        select(
            User.tg_id.label("user_id"),
            User.username.label("username"),
            User.premium_until.label("premium_until"),
            Virus.name.label("virus_name"),
            Virus.level.label("level"),
        )
        .join(Virus, Virus.owner_id == User.tg_id)
        .order_by(desc(Virus.level))
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.all()
    return [
        {
            "user_id": row.user_id,
            "username": row.username or str(row.user_id),
            "virus_name": row.virus_name,
            "level": row.level,
            "premium_until": row.premium_until,
        }
        for row in rows
    ]


async def get_top_immunity_level(session: AsyncSession, limit: int = 10) -> list[dict]:
    """
    Top players by immunity level.

    Returns list of {user_id, username, level, premium_until}.
    """
    stmt = (
        select(
            User.tg_id.label("user_id"),
            User.username.label("username"),
            User.premium_until.label("premium_until"),
            Immunity.level.label("level"),
        )
        .join(Immunity, Immunity.owner_id == User.tg_id)
        .order_by(desc(Immunity.level))
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.all()
    return [
        {
            "user_id": row.user_id,
            "username": row.username or str(row.user_id),
            "level": row.level,
            "premium_until": row.premium_until,
        }
        for row in rows
    ]


async def get_top_richest(session: AsyncSession, limit: int = 10) -> list[dict]:
    """
    Top players by bio_coins balance.

    Returns list of {user_id, username, bio_coins, premium_until}.
    """
    stmt = (
        select(
            User.tg_id.label("user_id"),
            User.username.label("username"),
            User.premium_until.label("premium_until"),
            User.bio_coins.label("bio_coins"),
        )
        .order_by(desc(User.bio_coins))
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.all()
    return [
        {
            "user_id": row.user_id,
            "username": row.username or str(row.user_id),
            "bio_coins": row.bio_coins,
            "premium_until": row.premium_until,
        }
        for row in rows
    ]
