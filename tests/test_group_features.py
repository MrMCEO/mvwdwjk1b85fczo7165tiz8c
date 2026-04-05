"""
Unit tests for new group-related features:
  1. get_random_target()          bot/services/combat.py
  2. smart_reply()                bot/utils/chat.py
  3. CallbackOwnerMiddleware      bot/middlewares/callback_owner.py
  4. ChatReportSettings model     bot/models/chat_settings.py
  5. should_notify_report() /
     toggle_report_notify()       bot/services/reports.py
  6. virus_name_entities()        bot/utils/emoji.py
  7. _parse_duration()            bot/handlers/moderation.py
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.moderation import _parse_duration
from bot.middlewares.callback_owner import CallbackOwnerMiddleware
from bot.models.chat_settings import ChatReportSettings
from bot.services.combat import get_random_target
from bot.services.player import create_player
from bot.services.reports import should_notify_report, toggle_report_notify
from bot.utils.chat import smart_reply
from bot.utils.emoji import virus_name_entities


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_message(chat_type: str = "private") -> MagicMock:
    """Create a minimal aiogram Message mock."""
    msg = MagicMock()
    msg.chat = MagicMock()
    msg.chat.type = chat_type
    msg.answer = AsyncMock(return_value=MagicMock())
    msg.reply = AsyncMock(return_value=MagicMock())
    return msg


def _make_callback(
    user_id: int,
    chat_type: str = "group",
    reply_user_id: int | None = None,
    inaccessible: bool = False,
) -> MagicMock:
    """Create a minimal aiogram CallbackQuery mock."""
    from aiogram.types import InaccessibleMessage

    cb = MagicMock()
    cb.from_user = MagicMock()
    cb.from_user.id = user_id
    cb.answer = AsyncMock()

    if inaccessible:
        # InaccessibleMessage requires a real Chat-compatible object.
        # Patch isinstance() so the middleware sees it as InaccessibleMessage.
        inacc_msg = MagicMock(spec=InaccessibleMessage)
        cb.message = inacc_msg
    else:
        cb.message = MagicMock()
        cb.message.chat = MagicMock()
        cb.message.chat.type = chat_type

        if reply_user_id is not None:
            reply_msg = MagicMock()
            reply_msg.from_user = MagicMock()
            reply_msg.from_user.id = reply_user_id
            cb.message.reply_to_message = reply_msg
        else:
            cb.message.reply_to_message = None

    return cb


# ---------------------------------------------------------------------------
# 1. get_random_target()
# ---------------------------------------------------------------------------


async def test_get_random_target_returns_other_player(session: AsyncSession):
    """Returns a random player that is not the attacker."""
    await create_player(session, tg_id=9001, username="rand_attacker")
    await create_player(session, tg_id=9002, username="rand_victim")

    target = await get_random_target(session, attacker_id=9001)

    assert target is not None
    assert target.tg_id == 9002


async def test_get_random_target_never_returns_self(session: AsyncSession):
    """get_random_target must never return the attacker."""
    await create_player(session, tg_id=9010, username="only_attacker_9010")

    target = await get_random_target(session, attacker_id=9010)

    # Only one user exists — should get None
    assert target is None


async def test_get_random_target_excludes_already_infected(session: AsyncSession):
    """get_random_target skips players already actively infected by this attacker."""
    from datetime import UTC, datetime

    from bot.models.infection import Infection

    await create_player(session, tg_id=9020, username="rand_atk_9020")
    await create_player(session, tg_id=9021, username="rand_vic_9021")
    # Third player that is NOT infected
    await create_player(session, tg_id=9022, username="rand_free_9022")

    # Infect 9021 by 9020
    infection = Infection(
        attacker_id=9020,
        victim_id=9021,
        started_at=datetime.now(UTC).replace(tzinfo=None),
        damage_per_tick=5.0,
        is_active=True,
    )
    session.add(infection)
    await session.flush()

    # With only two candidates (9021 infected, 9022 free),
    # get_random_target must return 9022.
    target = await get_random_target(session, attacker_id=9020)

    assert target is not None
    assert target.tg_id == 9022


async def test_get_random_target_none_when_all_infected(session: AsyncSession):
    """Returns None when all other players are already infected by the attacker."""
    from datetime import UTC, datetime

    from bot.models.infection import Infection

    await create_player(session, tg_id=9030, username="solo_atk_9030")
    await create_player(session, tg_id=9031, username="solo_vic_9031")

    infection = Infection(
        attacker_id=9030,
        victim_id=9031,
        started_at=datetime.now(UTC).replace(tzinfo=None),
        damage_per_tick=5.0,
        is_active=True,
    )
    session.add(infection)
    await session.flush()

    target = await get_random_target(session, attacker_id=9030)

    assert target is None


async def test_get_random_target_none_when_alone_in_db(session: AsyncSession):
    """Returns None when attacker is the only player in the database."""
    await create_player(session, tg_id=9040, username="loner_9040")

    target = await get_random_target(session, attacker_id=9040)

    assert target is None


async def test_get_random_target_inactive_infection_not_excluded(session: AsyncSession):
    """Inactive infections should NOT exclude the victim from being a target."""
    from datetime import UTC, datetime

    from bot.models.infection import Infection

    await create_player(session, tg_id=9050, username="atk_9050")
    await create_player(session, tg_id=9051, username="vic_9051")

    # Inactive infection — should NOT exclude 9051
    infection = Infection(
        attacker_id=9050,
        victim_id=9051,
        started_at=datetime.now(UTC).replace(tzinfo=None),
        damage_per_tick=5.0,
        is_active=False,  # <-- inactive
    )
    session.add(infection)
    await session.flush()

    target = await get_random_target(session, attacker_id=9050)

    assert target is not None
    assert target.tg_id == 9051


# ---------------------------------------------------------------------------
# 2. smart_reply()
# ---------------------------------------------------------------------------


async def test_smart_reply_private_calls_answer():
    """In private chat, smart_reply calls message.answer()."""
    msg = _make_message(chat_type="private")

    await smart_reply(msg, "hello")

    msg.answer.assert_called_once()
    msg.reply.assert_not_called()


async def test_smart_reply_group_calls_reply():
    """In group chat, smart_reply calls message.reply()."""
    msg = _make_message(chat_type="group")

    await smart_reply(msg, "hello")

    msg.reply.assert_called_once()
    msg.answer.assert_not_called()


async def test_smart_reply_supergroup_calls_reply():
    """In supergroup chat, smart_reply calls message.reply()."""
    msg = _make_message(chat_type="supergroup")

    await smart_reply(msg, "hello")

    msg.reply.assert_called_once()
    msg.answer.assert_not_called()


async def test_smart_reply_passes_text_and_markup():
    """smart_reply forwards text and reply_markup to the underlying method."""
    msg = _make_message(chat_type="private")
    markup = MagicMock()

    await smart_reply(msg, "test text", reply_markup=markup)

    call_kwargs = msg.answer.call_args
    assert "test text" in call_kwargs.args or call_kwargs.kwargs.get("text") == "test text" or call_kwargs.args[0] == "test text"
    assert markup in call_kwargs.args or call_kwargs.kwargs.get("reply_markup") == markup


# ---------------------------------------------------------------------------
# 3. CallbackOwnerMiddleware
# ---------------------------------------------------------------------------


async def test_callback_owner_private_skips_check():
    """In private chat, middleware passes through without checking owner."""
    middleware = CallbackOwnerMiddleware()
    handler = AsyncMock(return_value="ok")

    cb = _make_callback(user_id=1, chat_type="private")

    result = await middleware(handler, cb, {})

    handler.assert_called_once()
    cb.answer.assert_not_called()
    assert result == "ok"


async def test_callback_owner_group_owner_passes():
    """In group chat, middleware passes when user matches reply_to.from_user.id."""
    middleware = CallbackOwnerMiddleware()
    handler = AsyncMock(return_value="ok")

    cb = _make_callback(user_id=42, chat_type="group", reply_user_id=42)

    result = await middleware(handler, cb, {})

    handler.assert_called_once()
    cb.answer.assert_not_called()
    assert result == "ok"


async def test_callback_owner_group_wrong_user_blocked():
    """In group chat, middleware calls event.answer() when user != owner."""
    middleware = CallbackOwnerMiddleware()
    handler = AsyncMock(return_value="ok")

    # user 99 presses a button that was sent to user 42
    cb = _make_callback(user_id=99, chat_type="group", reply_user_id=42)

    result = await middleware(handler, cb, {})

    handler.assert_not_called()
    cb.answer.assert_called_once()
    assert "не ваша" in cb.answer.call_args.args[0]
    assert result is None


async def test_callback_owner_inaccessible_message_passes():
    """InaccessibleMessage should be treated as 'skip check'."""
    middleware = CallbackOwnerMiddleware()
    handler = AsyncMock(return_value="ok")

    cb = _make_callback(user_id=1, inaccessible=True)

    result = await middleware(handler, cb, {})

    handler.assert_called_once()
    assert result == "ok"


async def test_callback_owner_group_no_reply_to_passes():
    """In group without reply_to_message, middleware passes through."""
    middleware = CallbackOwnerMiddleware()
    handler = AsyncMock(return_value="ok")

    # reply_user_id=None → no reply_to_message set
    cb = _make_callback(user_id=7, chat_type="group", reply_user_id=None)

    result = await middleware(handler, cb, {})

    handler.assert_called_once()
    cb.answer.assert_not_called()


# ---------------------------------------------------------------------------
# 4. ChatReportSettings model
# ---------------------------------------------------------------------------


async def test_chat_report_settings_create(session: AsyncSession):
    """Can create a ChatReportSettings record."""
    await create_player(session, tg_id=8001, username="admin_crs")

    settings = ChatReportSettings(
        admin_id=8001,
        chat_id=-100001,
        notify_reports=True,
    )
    session.add(settings)
    await session.flush()

    result = await session.execute(
        select(ChatReportSettings).where(
            ChatReportSettings.admin_id == 8001,
            ChatReportSettings.chat_id == -100001,
        )
    )
    fetched = result.scalar_one_or_none()
    assert fetched is not None
    assert fetched.notify_reports is True


async def test_chat_report_settings_read_notify(session: AsyncSession):
    """Can read notify_reports from a ChatReportSettings record."""
    await create_player(session, tg_id=8002, username="admin_crs2")

    settings = ChatReportSettings(
        admin_id=8002,
        chat_id=-100002,
        notify_reports=False,
    )
    session.add(settings)
    await session.flush()

    result = await session.execute(
        select(ChatReportSettings).where(
            ChatReportSettings.admin_id == 8002,
            ChatReportSettings.chat_id == -100002,
        )
    )
    fetched = result.scalar_one()
    assert fetched.notify_reports is False


async def test_chat_report_settings_toggle(session: AsyncSession):
    """Can toggle notify_reports on an existing record."""
    await create_player(session, tg_id=8003, username="admin_crs3")

    settings = ChatReportSettings(
        admin_id=8003,
        chat_id=-100003,
        notify_reports=True,
    )
    session.add(settings)
    await session.flush()

    # Toggle
    settings.notify_reports = not settings.notify_reports
    await session.flush()

    result = await session.execute(
        select(ChatReportSettings).where(
            ChatReportSettings.admin_id == 8003,
            ChatReportSettings.chat_id == -100003,
        )
    )
    fetched = result.scalar_one()
    assert fetched.notify_reports is False


# ---------------------------------------------------------------------------
# 5. should_notify_report() and toggle_report_notify()
# ---------------------------------------------------------------------------


async def test_should_notify_report_default_true(session: AsyncSession):
    """New admin gets notify_reports=True by default."""
    await create_player(session, tg_id=8010, username="admin_notif_default")

    result = await should_notify_report(session, admin_id=8010, chat_id=-200001)

    assert result is True


async def test_should_notify_report_creates_record(session: AsyncSession):
    """should_notify_report creates a DB record when called for the first time."""
    await create_player(session, tg_id=8011, username="admin_notif_create")

    await should_notify_report(session, admin_id=8011, chat_id=-200002)

    db_result = await session.execute(
        select(ChatReportSettings).where(
            ChatReportSettings.admin_id == 8011,
            ChatReportSettings.chat_id == -200002,
        )
    )
    record = db_result.scalar_one_or_none()
    assert record is not None
    assert record.notify_reports is True


async def test_should_notify_report_existing_record(session: AsyncSession):
    """should_notify_report reads existing record without overwriting."""
    await create_player(session, tg_id=8012, username="admin_existing")

    existing = ChatReportSettings(
        admin_id=8012,
        chat_id=-200003,
        notify_reports=False,
    )
    session.add(existing)
    await session.flush()

    result = await should_notify_report(session, admin_id=8012, chat_id=-200003)

    assert result is False


async def test_toggle_report_notify_new_admin_returns_false(session: AsyncSession):
    """toggle_report_notify for new admin creates record with notify=False."""
    await create_player(session, tg_id=8020, username="admin_toggle_new")

    result = await toggle_report_notify(session, admin_id=8020, chat_id=-300001)

    assert result is False


async def test_toggle_report_notify_changes_value(session: AsyncSession):
    """toggle_report_notify flips an existing True → False."""
    await create_player(session, tg_id=8021, username="admin_toggle_flip")

    # Pre-create with notify=True
    existing = ChatReportSettings(
        admin_id=8021,
        chat_id=-300002,
        notify_reports=True,
    )
    session.add(existing)
    await session.flush()

    result = await toggle_report_notify(session, admin_id=8021, chat_id=-300002)

    assert result is False


async def test_toggle_report_notify_double_toggle_restores(session: AsyncSession):
    """Two toggles restore the original value."""
    await create_player(session, tg_id=8022, username="admin_double_toggle")

    existing = ChatReportSettings(
        admin_id=8022,
        chat_id=-300003,
        notify_reports=True,
    )
    session.add(existing)
    await session.flush()

    first = await toggle_report_notify(session, admin_id=8022, chat_id=-300003)
    second = await toggle_report_notify(session, admin_id=8022, chat_id=-300003)

    assert first is False
    assert second is True


# ---------------------------------------------------------------------------
# 6. virus_name_entities()
# ---------------------------------------------------------------------------


def test_virus_name_entities_no_json_returns_empty():
    """Returns empty list when entities_json is None."""
    result = virus_name_entities("My Virus", None)
    assert result == []


def test_virus_name_entities_empty_json_returns_empty():
    """Returns empty list when entities_json is empty JSON array."""
    result = virus_name_entities("My Virus", "[]")
    assert result == []


def test_virus_name_entities_returns_message_entity_list():
    """Returns a list with one MessageEntity for a single custom emoji."""
    entities_json = json.dumps([
        {"offset": 0, "length": 2, "custom_emoji_id": "5368324170671202286"},
    ])

    result = virus_name_entities("🦠X", entities_json, offset=0)

    assert len(result) == 1
    entity = result[0]
    assert entity.type == "custom_emoji"
    assert entity.offset == 0
    assert entity.length == 2
    assert entity.custom_emoji_id == "5368324170671202286"


def test_virus_name_entities_applies_offset():
    """Entities are shifted correctly when offset > 0."""
    entities_json = json.dumps([
        {"offset": 0, "length": 1, "custom_emoji_id": "123456789"},
    ])

    result = virus_name_entities("🦠", entities_json, offset=10)

    assert len(result) == 1
    assert result[0].offset == 10  # 0 + 10


def test_virus_name_entities_multiple_entities():
    """Handles multiple entities in the JSON."""
    entities_json = json.dumps([
        {"offset": 0, "length": 1, "custom_emoji_id": "111"},
        {"offset": 3, "length": 2, "custom_emoji_id": "222"},
    ])

    result = virus_name_entities("AB CD", entities_json, offset=5)

    assert len(result) == 2
    assert result[0].offset == 5   # 0 + 5
    assert result[1].offset == 8   # 3 + 5


def test_virus_name_entities_zero_offset_by_default():
    """Default offset is 0."""
    entities_json = json.dumps([
        {"offset": 2, "length": 1, "custom_emoji_id": "999"},
    ])

    result = virus_name_entities("AB🦠", entities_json)

    assert len(result) == 1
    assert result[0].offset == 2


# ---------------------------------------------------------------------------
# 7. _parse_duration()
# ---------------------------------------------------------------------------


def test_parse_duration_minutes():
    """'1min' → timedelta(minutes=1)."""
    assert _parse_duration("1min") == timedelta(minutes=1)


def test_parse_duration_multiple_minutes():
    """'30min' → timedelta(minutes=30)."""
    assert _parse_duration("30min") == timedelta(minutes=30)


def test_parse_duration_hours():
    """'1h' → timedelta(hours=1)."""
    assert _parse_duration("1h") == timedelta(hours=1)


def test_parse_duration_multiple_hours():
    """'12h' → timedelta(hours=12)."""
    assert _parse_duration("12h") == timedelta(hours=12)


def test_parse_duration_days():
    """'1d' → timedelta(days=1)."""
    assert _parse_duration("1d") == timedelta(days=1)


def test_parse_duration_multiple_days():
    """'7d' → timedelta(days=7)."""
    assert _parse_duration("7d") == timedelta(days=7)


def test_parse_duration_forever_returns_none():
    """'forever' → None (permanent)."""
    assert _parse_duration("forever") is None


def test_parse_duration_perm_returns_none():
    """'perm' → None (permanent)."""
    assert _parse_duration("perm") is None


def test_parse_duration_permanent_returns_none():
    """'permanent' → None (permanent)."""
    assert _parse_duration("permanent") is None


def test_parse_duration_999d_returns_none():
    """'999d' → None (treated as permanent)."""
    assert _parse_duration("999d") is None


def test_parse_duration_invalid_returns_none():
    """Invalid string → None."""
    assert _parse_duration("invalid") is None


def test_parse_duration_empty_returns_none():
    """Empty string → None."""
    assert _parse_duration("") is None


def test_parse_duration_case_insensitive_hours():
    """'2H' (uppercase) → timedelta(hours=2)."""
    assert _parse_duration("2H") == timedelta(hours=2)


def test_parse_duration_mins_variant():
    """'5mins' → timedelta(minutes=5)."""
    assert _parse_duration("5mins") == timedelta(minutes=5)


def test_parse_duration_minutes_variant():
    """'60minutes' → timedelta(minutes=60)."""
    assert _parse_duration("60minutes") == timedelta(minutes=60)


def test_parse_duration_hours_variant():
    """'2hours' → timedelta(hours=2)."""
    assert _parse_duration("2hours") == timedelta(hours=2)


def test_parse_duration_days_variant():
    """'3days' → timedelta(days=3)."""
    assert _parse_duration("3days") == timedelta(days=3)
