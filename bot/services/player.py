"""
Player service — user creation and profile retrieval.

Responsibilities:
  - create_player: atomically creates User + Virus + Immunity + all branch
    upgrades at level 0.
  - get_or_create_player: idempotent lookup / creation.
  - get_player_profile: full profile dict suitable for display in handlers.
"""

from __future__ import annotations

import logging

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models.immunity import Immunity, ImmunityBranch, ImmunityUpgrade
from bot.models.infection import Infection
from bot.models.user import User
from bot.models.virus import Virus, VirusBranch, VirusUpgrade

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default stats for a brand-new player
# ---------------------------------------------------------------------------

DEFAULT_VIRUS_NAME = "Неизвестный вирус"
DEFAULT_ATTACK_POWER = 10
DEFAULT_SPREAD_RATE = 1.0   # balanced: was 0.1, made attack_score=1 vs defense=10 (9% chance). Now 10 vs ~10.5 (~48%)
DEFAULT_MUTATION_POINTS = 0
DEFAULT_VIRUS_LEVEL = 0

DEFAULT_IMMUNITY_LEVEL = 0
DEFAULT_RESISTANCE = 10
DEFAULT_DETECTION_POWER = 0.1   # contributes 0.1*5=0.5 to defense_score at lvl0; grows with DETECTION upgrades
DEFAULT_RECOVERY_SPEED = 0.03   # balanced: was 0.1 (15% auto-cure with base 5%). Now 8% base auto-cure, ~12 ticks avg duration

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_user(session: AsyncSession, tg_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def create_player(
    session: AsyncSession,
    tg_id: int,
    username: str | None,
) -> User:
    """
    Create a brand-new player record.

    Creates:
      - User with default bio_coins = 0
      - Virus with default stats
      - VirusUpgrade rows for LETHALITY, CONTAGION, STEALTH (level=0, effect_value=0)
      - Immunity with default stats
      - ImmunityUpgrade rows for BARRIER, DETECTION, REGENERATION (level=0, effect_value=0)

    Flushes everything to the DB (but does NOT commit — caller decides).
    Returns the newly created User.
    """
    user = User(
        tg_id=tg_id,
        username=username or "",
        bio_coins=0,
        premium_coins=0,
    )
    session.add(user)
    await session.flush()  # get user.tg_id assigned (it's already known, but flush ensures FK consistency)

    # --- Virus ---
    virus = Virus(
        owner_id=tg_id,
        name=DEFAULT_VIRUS_NAME,
        level=DEFAULT_VIRUS_LEVEL,
        attack_power=DEFAULT_ATTACK_POWER,
        spread_rate=DEFAULT_SPREAD_RATE,
        mutation_points=DEFAULT_MUTATION_POINTS,
    )
    session.add(virus)
    await session.flush()  # need virus.id for VirusUpgrade FKs

    for branch in VirusBranch:
        v_upgrade = VirusUpgrade(
            virus_id=virus.id,
            branch=branch,
            level=0,
            effect_value=0.0,
        )
        session.add(v_upgrade)

    # --- Immunity ---
    immunity = Immunity(
        owner_id=tg_id,
        level=DEFAULT_IMMUNITY_LEVEL,
        resistance=DEFAULT_RESISTANCE,
        detection_power=DEFAULT_DETECTION_POWER,
        recovery_speed=DEFAULT_RECOVERY_SPEED,
    )
    session.add(immunity)
    await session.flush()  # need immunity.id for ImmunityUpgrade FKs

    for branch in ImmunityBranch:
        i_upgrade = ImmunityUpgrade(
            immunity_id=immunity.id,
            branch=branch,
            level=0,
            effect_value=0.0,
        )
        session.add(i_upgrade)

    await session.flush()

    logger.info("Created new player tg_id=%d username=%r", tg_id, username)
    return user


async def get_or_create_player(
    session: AsyncSession,
    tg_id: int,
    username: str | None,
) -> tuple[User, bool]:
    """
    Return (User, is_new) — fetch existing player or create a new one.

    Also updates the username if it has changed.
    Handles the race condition where two concurrent /start calls could
    both try to create the same user by catching IntegrityError.

    Returns:
        (user, True)  — freshly created player
        (user, False) — existing player
    """
    user = await _get_user(session, tg_id)
    if user is not None:
        # Keep username in sync
        new_name = username or ""
        if user.username != new_name:
            user.username = new_name
            await session.flush()
        return user, False

    try:
        return await create_player(session, tg_id, username), True
    except IntegrityError:
        # Another concurrent request already created the user — roll back
        # the failed nested operations and fetch the existing row.
        await session.rollback()
        user = await _get_user(session, tg_id)
        if user is None:
            raise  # unexpected — re-raise original error
        return user, False


async def get_player_profile(session: AsyncSession, user_id: int) -> dict:
    """
    Return a complete profile dict for *user_id*.

    Structure:
    {
        "user": {tg_id, username, bio_coins, premium_coins, created_at, last_active},
        "virus": {id, name, level, attack_power, spread_rate, mutation_points,
                  upgrades: {branch_name: {level, effect_value}}},
        "immunity": {id, level, resistance, detection_power, recovery_speed,
                     upgrades: {branch_name: {level, effect_value}}},
        "infections_sent_count": int,       # active outgoing
        "infections_received_count": int,   # active incoming
        "error": str   # only present on lookup failure
    }
    """
    # Load user with virus + immunity (and their upgrades) via selectinload
    result = await session.execute(
        select(User)
        .where(User.tg_id == user_id)
        .options(
            selectinload(User.virus).selectinload(Virus.upgrades),
            selectinload(User.immunity).selectinload(Immunity.upgrades),
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        return {"error": "Игрок не найден."}

    # Active outgoing infections
    sent_result = await session.execute(
        select(func.count(Infection.id)).where(
            and_(
                Infection.attacker_id == user_id,
                Infection.is_active == True,  # noqa: E712
            )
        )
    )
    infections_sent_count: int = sent_result.scalar_one()

    # Active incoming infections
    received_result = await session.execute(
        select(func.count(Infection.id)).where(
            and_(
                Infection.victim_id == user_id,
                Infection.is_active == True,  # noqa: E712
            )
        )
    )
    infections_received_count: int = received_result.scalar_one()

    # --- Virus section ---
    virus_data: dict = {}
    if user.virus is not None:
        v = user.virus
        virus_upgrades: dict[str, dict] = {}
        for u in v.upgrades:
            virus_upgrades[u.branch.value] = {
                "level": u.level,
                "effect_value": u.effect_value,
            }
        virus_data = {
            "id": v.id,
            "name": v.name,
            "name_entities_json": v.name_entities_json,
            "level": v.level,
            "attack_power": v.attack_power,
            "spread_rate": v.spread_rate,
            "mutation_points": v.mutation_points,
            "upgrades": virus_upgrades,
        }

    # --- Immunity section ---
    immunity_data: dict = {}
    if user.immunity is not None:
        im = user.immunity
        immunity_upgrades: dict[str, dict] = {}
        for u in im.upgrades:
            immunity_upgrades[u.branch.value] = {
                "level": u.level,
                "effect_value": u.effect_value,
            }
        immunity_data = {
            "id": im.id,
            "level": im.level,
            "resistance": im.resistance,
            "detection_power": im.detection_power,
            "recovery_speed": im.recovery_speed,
            "upgrades": immunity_upgrades,
        }

    return {
        "user": {
            "tg_id": user.tg_id,
            "username": user.username,
            "display_name": user.display_name,
            "bio_coins": user.bio_coins,
            "premium_coins": user.premium_coins,
            "created_at": user.created_at,
            "last_active": user.last_active,
            "premium_until": user.premium_until,
            "premium_prefix": user.premium_prefix,
        },
        "virus": virus_data,
        "immunity": immunity_data,
        "infections_sent_count": infections_sent_count,
        "infections_received_count": infections_received_count,
    }
