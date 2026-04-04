"""
Event service — server-wide temporary events (epidemics, boss fights, etc.).

Events affect ALL players while active:
  PANDEMIC        — boss-virus, players cooperate to defeat it
  GOLD_RUSH       — x2 resource mining
  ARMS_RACE       — -50% upgrade cost
  PLAGUE_SEASON   — +50% attack (infection) chance
  IMMUNITY_WAVE   — +50% defense for all
  MUTATION_STORM  — x3 mutation roll chance
  CEASEFIRE       — no one can attack

Modifier API:
  get_event_modifier(session, modifier_type) → float / bool
  Used by other services (resource.py, upgrade.py, combat.py, mutation.py)
  to apply event effects without coupling to this service.

Pandemic boss flow:
  1. Admin creates pandemic via start_pandemic().
  2. Players call attack_boss() with 30-min cooldown.
  3. When total damage >= boss_hp → event ends, rewards distributed.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models.event import Event, EventType, PandemicParticipant
from bot.models.resource import Currency as CurrencyType
from bot.models.resource import ResourceTransaction, TransactionReason
from bot.models.user import User
from bot.models.virus import Virus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default boss HP for pandemic events
DEFAULT_BOSS_HP: int = 10_000

# Cooldown between boss attacks per player
BOSS_ATTACK_COOLDOWN: timedelta = timedelta(minutes=30)

# Pandemic reward tiers (bio_coins)
REWARD_TIER_1: int = 1_000   # top-1
REWARD_TIER_2_3: int = 500   # top-2 and top-3
REWARD_ALL: int = 100        # every participant

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Core CRUD
# ---------------------------------------------------------------------------


async def create_event(
    session: AsyncSession,
    event_type: EventType,
    title: str,
    description: str,
    duration_hours: float,
    created_by: int | None = None,
) -> Event:
    """Create and persist a new event. Returns the newly created Event."""
    now = _now_utc()
    ends_at = now + timedelta(hours=duration_hours)

    event = Event(
        event_type=event_type,
        title=title,
        description=description,
        started_at=now,
        ends_at=ends_at,
        is_active=True,
        created_by=created_by,
    )
    session.add(event)
    await session.flush()
    logger.info(
        "Event created: id=%d type=%s ends_at=%s", event.id, event_type.value, ends_at
    )
    return event


async def get_active_events(session: AsyncSession) -> list[Event]:
    """Return all events that are currently active and not yet expired."""
    now = _now_utc()
    result = await session.execute(
        select(Event)
        .where(
            and_(
                Event.is_active == True,  # noqa: E712
                Event.ends_at > now,
            )
        )
        .order_by(Event.started_at.desc())
    )
    return list(result.scalars().all())


async def get_active_event_types(session: AsyncSession) -> set[EventType]:
    """Return the set of active EventType values (for fast membership checks)."""
    events = await get_active_events(session)
    return {e.event_type for e in events}


async def get_event_by_id(session: AsyncSession, event_id: int) -> Event | None:
    """Return an event by its primary key."""
    result = await session.execute(select(Event).where(Event.id == event_id))
    return result.scalar_one_or_none()


async def expire_events(session: AsyncSession) -> int:
    """
    Deactivate all events whose ends_at has passed.

    Returns the count of events deactivated.
    """
    now = _now_utc()
    result = await session.execute(
        select(Event).where(
            and_(
                Event.is_active == True,  # noqa: E712
                Event.ends_at <= now,
            )
        )
    )
    expired = list(result.scalars().all())
    for event in expired:
        event.is_active = False

    if expired:
        await session.flush()
        logger.info("Expired %d event(s).", len(expired))

    return len(expired)


async def stop_event(session: AsyncSession, event_id: int) -> bool:
    """
    Manually deactivate an event (admin action).

    Returns True if the event was found and deactivated, False otherwise.
    """
    event = await get_event_by_id(session, event_id)
    if event is None or not event.is_active:
        return False
    event.is_active = False
    await session.flush()
    return True


# ---------------------------------------------------------------------------
# Modifier API — used by other services
# ---------------------------------------------------------------------------

_EVENT_MODIFIER_MAP: dict[str, tuple[EventType, float | bool]] = {
    "mining_mult":          (EventType.GOLD_RUSH,     2.0),
    "upgrade_cost_mult":    (EventType.ARMS_RACE,     0.5),
    "attack_chance_mult":   (EventType.PLAGUE_SEASON, 1.5),
    "defense_mult":         (EventType.IMMUNITY_WAVE, 1.5),
    "mutation_chance_mult": (EventType.MUTATION_STORM, 3.0),
}


async def get_event_modifier(session: AsyncSession, modifier_type: str) -> float | bool:
    """
    Return the current modifier value for the given modifier_type.

    modifier_type values and their defaults:
      "mining_mult"           → 2.0 if GOLD_RUSH active,         else 1.0
      "upgrade_cost_mult"     → 0.5 if ARMS_RACE active,         else 1.0
      "attack_chance_mult"    → 1.5 if PLAGUE_SEASON active,     else 1.0
      "defense_mult"          → 1.5 if IMMUNITY_WAVE active,     else 1.0
      "mutation_chance_mult"  → 3.0 if MUTATION_STORM active,    else 1.0
      "can_attack"            → False if CEASEFIRE active,        else True
    """
    if modifier_type == "can_attack":
        active_types = await get_active_event_types(session)
        return EventType.CEASEFIRE not in active_types

    mapping = _EVENT_MODIFIER_MAP.get(modifier_type)
    if mapping is None:
        return 1.0  # unknown modifier — neutral

    event_type, active_value = mapping
    active_types = await get_active_event_types(session)
    return active_value if event_type in active_types else 1.0


# ---------------------------------------------------------------------------
# PANDEMIC — boss fight
# ---------------------------------------------------------------------------


async def start_pandemic(
    session: AsyncSession,
    boss_hp: int = DEFAULT_BOSS_HP,
    duration_hours: int = 24,
    created_by: int | None = None,
) -> Event:
    """
    Create a PANDEMIC event with the given boss HP.

    The boss HP is stored as part of the description so it can be parsed back
    without requiring a schema change.
    """
    description = (
        f"Босс-вирус атакует! Суммарный HP: {boss_hp:,}.\n"
        f"Объединитесь, чтобы победить его!\n"
        f"boss_hp={boss_hp}"  # machine-parseable tag at the end
    )
    return await create_event(
        session=session,
        event_type=EventType.PANDEMIC,
        title="Пандемия — Босс-вирус",
        description=description,
        duration_hours=duration_hours,
        created_by=created_by,
    )


def _parse_boss_hp(event: Event) -> int:
    """Extract boss HP from the description tag 'boss_hp=N'."""
    for line in event.description.splitlines():
        if line.startswith("boss_hp="):
            try:
                return int(line.split("=", 1)[1])
            except ValueError:
                pass
    return DEFAULT_BOSS_HP


async def _get_or_create_participant(
    session: AsyncSession, event_id: int, user_id: int
) -> PandemicParticipant:
    """Return existing participant row or create a new one."""
    result = await session.execute(
        select(PandemicParticipant)
        .where(
            and_(
                PandemicParticipant.event_id == event_id,
                PandemicParticipant.user_id == user_id,
            )
        )
        .with_for_update()
    )
    participant = result.scalar_one_or_none()
    if participant is None:
        participant = PandemicParticipant(
            event_id=event_id,
            user_id=user_id,
            damage_dealt=0,
            last_attack_at=None,
            joined_at=_now_utc(),
        )
        session.add(participant)
        await session.flush()
    return participant


async def _total_damage_dealt(session: AsyncSession, event_id: int) -> int:
    """Return sum of all damage dealt to the boss in this event."""
    result = await session.execute(
        select(func.coalesce(func.sum(PandemicParticipant.damage_dealt), 0)).where(
            PandemicParticipant.event_id == event_id
        )
    )
    return int(result.scalar())


async def attack_boss(
    session: AsyncSession,
    user_id: int,
    event_id: int,
) -> tuple[int, str]:
    """
    Player attacks the pandemic boss.

    Returns (damage_dealt, message).
    damage_dealt is 0 on failure.

    Attack power = virus.attack_power * (1 + sum of all virus upgrade levels)
    Cooldown: 30 minutes between attacks.
    If total damage >= boss_hp → event ends and rewards are distributed.
    """
    # Load event
    event = await get_event_by_id(session, event_id)
    if event is None or not event.is_active or event.event_type != EventType.PANDEMIC:
        return 0, "Ивент пандемии не найден или уже завершён."

    now = _now_utc()
    if event.ends_at <= now:
        event.is_active = False
        await session.flush()
        return 0, "Пандемия уже закончилась."

    # Get or create participant row (with row lock)
    participant = await _get_or_create_participant(session, event_id, user_id)

    # Cooldown check
    if participant.last_attack_at is not None:
        elapsed = now - participant.last_attack_at
        if elapsed < BOSS_ATTACK_COOLDOWN:
            remaining = BOSS_ATTACK_COOLDOWN - elapsed
            minutes = int(remaining.total_seconds() // 60)
            seconds = int(remaining.total_seconds() % 60)
            return 0, (
                f"Кулдаун атаки на босса ещё не истёк. "
                f"Следующая атака через {minutes}м {seconds}с."
            )

    # Load attacker's virus with upgrades
    virus_result = await session.execute(
        select(Virus)
        .where(Virus.owner_id == user_id)
        .options(selectinload(Virus.upgrades))
    )
    virus: Virus | None = virus_result.scalar_one_or_none()
    if virus is None:
        return 0, "У тебя ещё нет вируса. Создай профиль через /start."

    # Calculate damage
    upgrade_level_sum = sum(u.level for u in virus.upgrades)
    damage = int(virus.attack_power * (1 + upgrade_level_sum))
    damage = max(1, damage)  # at least 1 damage

    # Apply damage
    participant.damage_dealt += damage
    participant.last_attack_at = now
    await session.flush()

    # Check if boss is defeated
    boss_hp = _parse_boss_hp(event)
    total_damage = await _total_damage_dealt(session, event_id)

    if total_damage >= boss_hp:
        event.is_active = False
        await session.flush()
        await distribute_pandemic_rewards(session, event_id)
        return damage, (
            f"Ты нанёс {damage} урона боссу! "
            f"Босс повержён! Суммарный урон: {total_damage:,}/{boss_hp:,}.\n"
            f"Награды розданы всем участникам!"
        )

    remaining_hp = boss_hp - total_damage
    return damage, (
        f"Ты нанёс <b>{damage}</b> урона боссу!\n"
        f"Суммарный урон: <b>{total_damage:,}/{boss_hp:,}</b>\n"
        f"Осталось HP боссу: <b>{remaining_hp:,}</b>"
    )


async def get_pandemic_leaderboard(
    session: AsyncSession,
    event_id: int,
    limit: int = 10,
) -> list[dict]:
    """
    Return top participants for the given pandemic event.

    Each entry: {"rank": int, "user_id": int, "username": str, "damage": int}
    """
    result = await session.execute(
        select(PandemicParticipant, User)
        .join(User, User.tg_id == PandemicParticipant.user_id)
        .where(PandemicParticipant.event_id == event_id)
        .order_by(PandemicParticipant.damage_dealt.desc())
        .limit(limit)
    )
    rows = result.all()

    leaderboard = []
    for rank, (participant, user) in enumerate(rows, start=1):
        leaderboard.append(
            {
                "rank": rank,
                "user_id": user.tg_id,
                "username": user.username or str(user.tg_id),
                "damage": participant.damage_dealt,
            }
        )
    return leaderboard


async def distribute_pandemic_rewards(session: AsyncSession, event_id: int) -> None:
    """
    Distribute rewards to all pandemic participants.

    Top-1:   +1000 bio_coins
    Top 2-3: +500  bio_coins
    All:     +100  bio_coins (base reward)

    Top players get BOTH the tier reward AND the base reward.
    """
    leaderboard = await get_pandemic_leaderboard(session, event_id, limit=None)

    if not leaderboard:
        return

    for entry in leaderboard:
        user_id = entry["user_id"]
        rank = entry["rank"]

        # Determine reward amount
        if rank == 1:
            amount = REWARD_TIER_1 + REWARD_ALL
        elif rank in (2, 3):
            amount = REWARD_TIER_2_3 + REWARD_ALL
        else:
            amount = REWARD_ALL

        # Load and update user balance
        user_result = await session.execute(
            select(User).where(User.tg_id == user_id).with_for_update()
        )
        user: User | None = user_result.scalar_one_or_none()
        if user is None:
            continue

        user.bio_coins += amount
        tx = ResourceTransaction(
            user_id=user_id,
            amount=amount,
            currency=CurrencyType.BIO_COINS,
            reason=TransactionReason.MINING,  # closest generic reason
        )
        session.add(tx)

    await session.flush()
    logger.info("Pandemic rewards distributed for event_id=%d.", event_id)
