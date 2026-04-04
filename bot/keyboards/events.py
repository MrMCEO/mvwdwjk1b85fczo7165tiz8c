"""Events section keyboards."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.models.event import Event, EventType

# Эмодзи по типу ивента
EVENT_EMOJI: dict[EventType, str] = {
    EventType.PANDEMIC:      "💀",
    EventType.GOLD_RUSH:     "💎",
    EventType.ARMS_RACE:     "🔧",
    EventType.PLAGUE_SEASON: "☣️",
    EventType.IMMUNITY_WAVE: "💉",
    EventType.MUTATION_STORM: "🧬",
    EventType.CEASEFIRE:     "🕊",
}

# Русские названия типов (на случай если title не задан)
EVENT_TYPE_LABELS: dict[EventType, str] = {
    EventType.PANDEMIC:      "Пандемия",
    EventType.GOLD_RUSH:     "Золотая лихорадка",
    EventType.ARMS_RACE:     "Гонка вооружений",
    EventType.PLAGUE_SEASON: "Сезон чумы",
    EventType.IMMUNITY_WAVE: "Волна иммунитета",
    EventType.MUTATION_STORM: "Буря мутаций",
    EventType.CEASEFIRE:     "Перемирие",
}


def events_menu_kb(events: list[Event]) -> InlineKeyboardMarkup:
    """
    Menu listing all active events.

    Each event is shown as a button with its type emoji and title.
    Clicking opens the event info screen.
    """
    builder = InlineKeyboardBuilder()

    if not events:
        builder.button(
            text="— Активных ивентов нет —",
            callback_data="events_menu",
        )
    else:
        for event in events:
            emoji = EVENT_EMOJI.get(event.event_type, "🌍")
            builder.button(
                text=f"{emoji} {event.title}",
                callback_data=f"event_info_{event.id}",
            )

    builder.button(text="◀️ Назад", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()


def event_info_kb(event: Event, is_pandemic: bool = False) -> InlineKeyboardMarkup:
    """
    Event detail view keyboard.

    For pandemic events: adds "Атаковать босса" and "Таблица лидеров" buttons.
    For regular events:  adds "Таблица лидеров" button.
    """
    builder = InlineKeyboardBuilder()

    if is_pandemic:
        builder.button(
            text="💀 Атаковать босса",
            callback_data=f"pandemic_attack_{event.id}",
        )
        builder.button(
            text="🏆 Таблица лидеров",
            callback_data=f"pandemic_leaderboard_{event.id}",
        )
    else:
        builder.button(
            text="🏆 Таблица лидеров",
            callback_data=f"event_leaderboard_{event.id}",
        )

    builder.button(text="◀️ К ивентам", callback_data="events_menu")
    builder.adjust(1)
    return builder.as_markup()


def pandemic_kb(event_id: int) -> InlineKeyboardMarkup:
    """
    Pandemic boss fight keyboard.

    Buttons: Атаковать, Таблица лидеров, Назад.
    """
    builder = InlineKeyboardBuilder()
    builder.button(
        text="💀 Атаковать",
        callback_data=f"pandemic_attack_{event_id}",
    )
    builder.button(
        text="🏆 Таблица лидеров",
        callback_data=f"pandemic_leaderboard_{event_id}",
    )
    builder.button(
        text="◀️ К ивентам",
        callback_data="events_menu",
    )
    builder.adjust(1)
    return builder.as_markup()
