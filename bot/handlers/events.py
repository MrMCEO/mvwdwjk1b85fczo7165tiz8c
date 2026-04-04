"""
Events handler — server-wide temporary events (epidemics, boss fights, etc.).

Player callbacks:
  events_menu              — list active events
  event_info_{id}          — event detail view
  pandemic_attack_{id}     — attack the pandemic boss
  pandemic_leaderboard_{id}— top participants of a pandemic

Admin commands (requires admin_ids from config):
  /event_create {type} {hours} {title}  — create an event
  /event_stop {id}                      — stop an event
  /pandemic {hours} {boss_hp}           — launch a pandemic
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from html import escape

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.keyboards.events import (
    EVENT_EMOJI,
    EVENT_TYPE_LABELS,
    event_info_kb,
    events_menu_kb,
    pandemic_kb,
)
from bot.models.event import EventType
from bot.services.event import (
    DEFAULT_BOSS_HP,
    attack_boss,
    create_event,
    get_active_events,
    get_event_by_id,
    get_pandemic_leaderboard,
    start_pandemic,
    stop_event,
)

router = Router(name="events")
logger = logging.getLogger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Map string keys (from /event_create command) to EventType values
_TYPE_ALIASES: dict[str, EventType] = {
    "pandemic":      EventType.PANDEMIC,
    "gold_rush":     EventType.GOLD_RUSH,
    "arms_race":     EventType.ARMS_RACE,
    "plague_season": EventType.PLAGUE_SEASON,
    "immunity_wave": EventType.IMMUNITY_WAVE,
    "mutation_storm": EventType.MUTATION_STORM,
    "ceasefire":     EventType.CEASEFIRE,
}


def _fmt_time_remaining(ends_at: datetime) -> str:
    """Human-readable time until event ends."""
    now = datetime.now(UTC).replace(tzinfo=None)
    delta = ends_at - now
    if delta.total_seconds() <= 0:
        return "завершён"
    total_seconds = int(delta.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if hours >= 24:
        days = hours // 24
        hours_rem = hours % 24
        return f"{days}д {hours_rem}ч"
    if hours > 0:
        return f"{hours}ч {minutes}м"
    return f"{minutes}м"


def _fmt_events_list(events: list) -> str:
    if not events:
        return (
            "🌍 <b>Ивенты</b>\n\n"
            "Сейчас нет активных ивентов.\n\n"
            "Возвращайся позже — администраторы регулярно запускают события!"
        )

    lines = ["🌍 <b>Активные ивенты</b>\n"]
    for event in events:
        emoji = EVENT_EMOJI.get(event.event_type, "🌍")
        remaining = _fmt_time_remaining(event.ends_at)
        lines.append(f"{emoji} <b>{escape(event.title)}</b> — <i>осталось {remaining}</i>")
    lines.append("\nНажми на ивент для подробностей.")
    return "\n".join(lines)


def _fmt_event_detail(event) -> str:
    emoji = EVENT_EMOJI.get(event.event_type, "🌍")
    type_label = EVENT_TYPE_LABELS.get(event.event_type, event.event_type.value)
    remaining = _fmt_time_remaining(event.ends_at)
    started = event.started_at.strftime("%d.%m.%Y %H:%M") if event.started_at else "—"
    ends = event.ends_at.strftime("%d.%m.%Y %H:%M") if event.ends_at else "—"

    # Strip machine-parseable tag from description for display
    desc_lines = [
        line for line in event.description.splitlines()
        if not line.startswith("boss_hp=")
    ]
    description = "\n".join(desc_lines).strip()

    lines = [
        f"{emoji} <b>{escape(event.title)}</b>",
        f"Тип: <b>{type_label}</b>",
        "",
    ]
    if description:
        lines.append(description)
        lines.append("")

    lines += [
        f"🕐 Начало: {started} UTC",
        f"🕐 Конец:  {ends} UTC",
        f"⏳ Осталось: <b>{remaining}</b>",
    ]
    return "\n".join(lines)


def _fmt_leaderboard(leaderboard: list[dict], event_title: str) -> str:
    lines = [f"🏆 <b>Таблица лидеров — {escape(event_title)}</b>\n"]

    if not leaderboard:
        lines.append("Ещё никто не атаковал босса.")
        return "\n".join(lines)

    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    for entry in leaderboard:
        rank = entry["rank"]
        medal = medals.get(rank, f"{rank}.")
        username = escape(entry["username"])
        damage = entry["damage"]
        lines.append(f"{medal} <b>{username}</b> — {damage:,} урона")

    return "\n".join(lines)


def _is_admin(user_id: int) -> bool:
    return user_id in settings.admin_ids


# ---------------------------------------------------------------------------
# Player callbacks
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "events_menu")
async def cb_events_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show list of active events."""
    events = await get_active_events(session)
    text = _fmt_events_list(events)
    await callback.message.edit_text(
        text,
        reply_markup=events_menu_kb(events),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("event_info_"))
async def cb_event_info(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show detailed info about a specific event."""
    try:
        event_id = int(callback.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback.answer("Неверный ID ивента.", show_alert=True)
        return

    event = await get_event_by_id(session, event_id)
    if event is None or not event.is_active:
        await callback.answer("Ивент не найден или уже завершён.", show_alert=True)
        events = await get_active_events(session)
        await callback.message.edit_text(
            _fmt_events_list(events),
            reply_markup=events_menu_kb(events),
            parse_mode="HTML",
        )
        return

    is_pandemic = event.event_type == EventType.PANDEMIC
    text = _fmt_event_detail(event)
    await callback.message.edit_text(
        text,
        reply_markup=event_info_kb(event, is_pandemic=is_pandemic),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("pandemic_attack_"))
async def cb_pandemic_attack(callback: CallbackQuery, session: AsyncSession) -> None:
    """Player attacks the pandemic boss."""
    try:
        event_id = int(callback.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback.answer("Неверный ID ивента.", show_alert=True)
        return

    user_id = callback.from_user.id
    damage, message = await attack_boss(session, user_id, event_id)
    await session.commit()

    await callback.answer(message[:200], show_alert=True)

    # Refresh the event detail view
    event = await get_event_by_id(session, event_id)
    if event is not None and event.is_active:
        text = _fmt_event_detail(event)
        await callback.message.edit_text(
            text,
            reply_markup=pandemic_kb(event_id),
            parse_mode="HTML",
        )
    else:
        # Event ended — show events menu
        events = await get_active_events(session)
        await callback.message.edit_text(
            _fmt_events_list(events),
            reply_markup=events_menu_kb(events),
            parse_mode="HTML",
        )


@router.callback_query(lambda c: c.data and c.data.startswith("pandemic_leaderboard_"))
async def cb_pandemic_leaderboard(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show pandemic boss leaderboard."""
    try:
        event_id = int(callback.data.split("_")[-1])
    except (ValueError, IndexError):
        await callback.answer("Неверный ID ивента.", show_alert=True)
        return

    event = await get_event_by_id(session, event_id)
    if event is None:
        await callback.answer("Ивент не найден.", show_alert=True)
        return

    leaderboard = await get_pandemic_leaderboard(session, event_id, limit=10)
    text = _fmt_leaderboard(leaderboard, event.title)

    await callback.message.edit_text(
        text,
        reply_markup=pandemic_kb(event_id),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Admin commands
# ---------------------------------------------------------------------------


@router.message(Command("event_create"))
async def cmd_event_create(message: Message, session: AsyncSession) -> None:
    """
    Admin: /event_create {type} {hours} {title}

    Example: /event_create gold_rush 12 Золотая лихорадка выходного дня
    Valid types: pandemic, gold_rush, arms_race, plague_season,
                 immunity_wave, mutation_storm, ceasefire
    """
    if not _is_admin(message.from_user.id):
        await message.answer("❌ Недостаточно прав.")
        return

    args = message.text.split(maxsplit=3)[1:]  # skip the command itself
    if len(args) < 3:
        await message.answer(
            "Использование: /event_create {тип} {часы} {название}\n\n"
            "Доступные типы: pandemic, gold_rush, arms_race, plague_season, "
            "immunity_wave, mutation_storm, ceasefire\n\n"
            "Пример: /event_create gold_rush 12 Золотая лихорадка"
        )
        return

    type_str, hours_str, title = args[0], args[1], args[2]

    event_type = _TYPE_ALIASES.get(type_str.lower())
    if event_type is None:
        await message.answer(
            f"❌ Неизвестный тип ивента: {escape(type_str)}\n\n"
            "Доступные типы: " + ", ".join(_TYPE_ALIASES.keys())
        )
        return

    try:
        duration_hours = float(hours_str)
        if duration_hours <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Количество часов должно быть положительным числом.")
        return

    if event_type == EventType.PANDEMIC:
        event = await start_pandemic(
            session,
            boss_hp=DEFAULT_BOSS_HP,
            duration_hours=int(duration_hours),
            created_by=message.from_user.id,
        )
    else:
        emoji = EVENT_EMOJI.get(event_type, "🌍")
        type_label = EVENT_TYPE_LABELS.get(event_type, event_type.value)
        event = await create_event(
            session=session,
            event_type=event_type,
            title=title,
            description=f"Активное событие: {type_label}.",
            duration_hours=duration_hours,
            created_by=message.from_user.id,
        )

    await session.commit()
    emoji = EVENT_EMOJI.get(event_type, "🌍")
    await message.answer(
        f"✅ Ивент создан!\n\n"
        f"{emoji} <b>{escape(event.title)}</b>\n"
        f"ID: {event.id}\n"
        f"Тип: {event.event_type.value}\n"
        f"Длительность: {duration_hours}ч",
        parse_mode="HTML",
    )


@router.message(Command("event_stop"))
async def cmd_event_stop(message: Message, session: AsyncSession) -> None:
    """Admin: /event_stop {id}"""
    if not _is_admin(message.from_user.id):
        await message.answer("❌ Недостаточно прав.")
        return

    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Использование: /event_stop {ID ивента}")
        return

    try:
        event_id = int(parts[1])
    except ValueError:
        await message.answer("❌ ID ивента должен быть числом.")
        return

    success = await stop_event(session, event_id)
    await session.commit()

    if success:
        await message.answer(f"✅ Ивент #{event_id} остановлен.")
    else:
        await message.answer(f"❌ Ивент #{event_id} не найден или уже завершён.")


@router.message(Command("pandemic"))
async def cmd_pandemic(message: Message, session: AsyncSession) -> None:
    """
    Admin: /pandemic {hours} {boss_hp}

    Example: /pandemic 24 10000
    """
    if not _is_admin(message.from_user.id):
        await message.answer("❌ Недостаточно прав.")
        return

    parts = message.text.split()
    hours = int(parts[1]) if len(parts) > 1 else 24
    boss_hp = int(parts[2]) if len(parts) > 2 else DEFAULT_BOSS_HP

    if hours <= 0 or boss_hp <= 0:
        await message.answer("❌ Количество часов и HP босса должны быть > 0.")
        return

    event = await start_pandemic(
        session,
        boss_hp=boss_hp,
        duration_hours=hours,
        created_by=message.from_user.id,
    )
    await session.commit()

    await message.answer(
        f"💀 <b>Пандемия запущена!</b>\n\n"
        f"ID ивента: {event.id}\n"
        f"HP босса: {boss_hp:,}\n"
        f"Длительность: {hours}ч",
        parse_mode="HTML",
    )
