"""
Unit tests for bot/services/event.py
"""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.event import Event, EventType
from bot.services.event import (
    create_event,
    expire_events,
    get_active_events,
    get_event_modifier,
)


async def test_create_event(session: AsyncSession):
    """create_event persists a new event and returns it."""
    event = await create_event(
        session,
        event_type=EventType.GOLD_RUSH,
        title="Золотая лихорадка",
        description="x2 добыча",
        duration_hours=2.0,
    )
    assert event.id is not None
    assert event.event_type == EventType.GOLD_RUSH
    assert event.is_active is True
    assert event.ends_at > event.started_at


async def test_get_active_events_returns_event(session: AsyncSession):
    """An active event is returned by get_active_events."""
    await create_event(
        session,
        event_type=EventType.ARMS_RACE,
        title="Гонка вооружений",
        description="-50% upgrade cost",
        duration_hours=3.0,
    )

    active = await get_active_events(session)
    types = {e.event_type for e in active}
    assert EventType.ARMS_RACE in types


async def test_get_event_modifier_gold_rush(session: AsyncSession):
    """get_event_modifier returns 2.0 for mining_mult during GOLD_RUSH."""
    # No events active initially
    mult_before = await get_event_modifier(session, "mining_mult")
    assert mult_before == 1.0

    await create_event(
        session,
        event_type=EventType.GOLD_RUSH,
        title="Золотая лихорадка",
        description="test",
        duration_hours=1.0,
    )

    mult_after = await get_event_modifier(session, "mining_mult")
    assert mult_after == 2.0


async def test_get_event_modifier_unknown_returns_1(session: AsyncSession):
    """Unknown modifier type returns 1.0 (neutral)."""
    val = await get_event_modifier(session, "nonexistent_modifier")
    assert val == 1.0


async def test_get_event_modifier_ceasefire(session: AsyncSession):
    """can_attack returns False when CEASEFIRE is active."""
    can_attack_before = await get_event_modifier(session, "can_attack")
    assert can_attack_before is True

    await create_event(
        session,
        event_type=EventType.CEASEFIRE,
        title="Перемирие",
        description="no attacks",
        duration_hours=1.0,
    )

    can_attack_after = await get_event_modifier(session, "can_attack")
    assert can_attack_after is False


async def test_expire_events_deactivates_old_events(session: AsyncSession):
    """expire_events deactivates events whose ends_at has passed."""
    now = datetime.now(UTC).replace(tzinfo=None)

    # Create an already-expired event by inserting directly
    expired_event = Event(
        event_type=EventType.MUTATION_STORM,
        title="Шторм мутаций",
        description="x3 mutation chance",
        started_at=now - timedelta(hours=2),
        ends_at=now - timedelta(hours=1),
        is_active=True,
        created_by=None,
    )
    session.add(expired_event)
    await session.flush()

    count, _notifications = await expire_events(session)
    assert count >= 1

    await session.refresh(expired_event)
    assert expired_event.is_active is False


async def test_expire_events_leaves_active_intact(session: AsyncSession):
    """expire_events does not touch still-active events."""
    event = await create_event(
        session,
        event_type=EventType.PLAGUE_SEASON,
        title="Чумной сезон",
        description="test active",
        duration_hours=10.0,
    )

    await expire_events(session)

    await session.refresh(event)
    assert event.is_active is True
