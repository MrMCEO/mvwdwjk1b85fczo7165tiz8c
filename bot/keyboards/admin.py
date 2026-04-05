"""Admin panel keyboards."""

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.models.event import EventType

# ---------------------------------------------------------------------------
# Event type display data
# ---------------------------------------------------------------------------

EVENT_EMOJI: dict[EventType, str] = {
    EventType.PANDEMIC:       "💀",
    EventType.GOLD_RUSH:      "💎",
    EventType.ARMS_RACE:      "🔧",
    EventType.PLAGUE_SEASON:  "☣️",
    EventType.IMMUNITY_WAVE:  "💉",
    EventType.MUTATION_STORM: "🧬",
    EventType.CEASEFIRE:      "🕊",
}

EVENT_NAMES: dict[EventType, str] = {
    EventType.PANDEMIC:       "Пандемия",
    EventType.GOLD_RUSH:      "Золотая лихорадка",
    EventType.ARMS_RACE:      "Гонка вооружений",
    EventType.PLAGUE_SEASON:  "Сезон чумы",
    EventType.IMMUNITY_WAVE:  "Волна иммунитета",
    EventType.MUTATION_STORM: "Мутационный шторм",
    EventType.CEASEFIRE:      "Перемирие",
}


def admin_menu_kb() -> InlineKeyboardMarkup:
    """Main admin panel navigation keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Промокоды",    callback_data="admin_promos")
    builder.button(text="🔍 Найти игрока", callback_data="admin_find_player")
    builder.button(text="💰 Выдать валюту", callback_data="admin_give_start")
    builder.button(text="📊 Статистика",   callback_data="admin_stats")
    builder.button(text="🌍 Ивенты",       callback_data="admin_events")
    builder.adjust(2, 2, 1)
    return builder.as_markup()


def admin_promos_kb(promos: list[dict]) -> InlineKeyboardMarkup:
    """List of promo codes + create help button."""
    builder = InlineKeyboardBuilder()
    for p in promos[:10]:
        status = "✅" if p["is_active"] and not p["expired"] else "❌"
        limit_str = (
            f"{p['current_activations']}/{p['max_activations']}"
            if p["max_activations"] > 0
            else f"{p['current_activations']}/∞"
        )
        builder.button(
            text=f"{status} {p['code']} ({limit_str})",
            callback_data=f"admin_promo_info_{p['code']}",
        )
    builder.button(text="🔙 Назад", callback_data="admin_menu")
    builder.adjust(1)
    return builder.as_markup()


def admin_promo_detail_kb(code: str, is_active: bool) -> InlineKeyboardMarkup:
    """Per-promo action keyboard."""
    builder = InlineKeyboardBuilder()
    if is_active:
        builder.button(text="🗑 Деактивировать", callback_data=f"admin_promo_del_{code}", style=ButtonStyle.DANGER)
    builder.button(text="🔙 Промокоды", callback_data="admin_promos")
    builder.adjust(1)
    return builder.as_markup()


def admin_player_kb(user_id: int) -> InlineKeyboardMarkup:
    """Per-player action keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Логи прокачки",     callback_data=f"admin_logs_{user_id}_upgrades")
    builder.button(text="⚔️ Логи атак",         callback_data=f"admin_logs_{user_id}_attacks")
    builder.button(text="💰 Логи транзакций",   callback_data=f"admin_logs_{user_id}_purchases")
    builder.button(text="💵 Выдать валюту",      callback_data=f"admin_give_{user_id}",   style=ButtonStyle.SUCCESS)
    builder.button(text="⚙️ Установить баланс",  callback_data=f"admin_setbal_{user_id}")
    builder.button(text="◀️ Назад",              callback_data="admin_find_player")
    builder.adjust(3, 2, 1)
    return builder.as_markup()


def admin_logs_kb(user_id: int, log_type: str) -> InlineKeyboardMarkup:
    """Log type filter buttons with active indicator."""
    types = [
        ("all",       "Все"),
        ("upgrades",  "Прокачка"),
        ("attacks",   "Атаки"),
        ("purchases", "Покупки"),
    ]
    builder = InlineKeyboardBuilder()
    for key, label in types:
        prefix = "▶️ " if key == log_type else ""
        builder.button(
            text=f"{prefix}{label}",
            callback_data=f"admin_logs_{user_id}_{key}",
        )
    builder.button(text="◀️ Назад", callback_data=f"admin_player_{user_id}")
    builder.adjust(4, 1)
    return builder.as_markup()


def cancel_kb() -> InlineKeyboardMarkup:
    """Single cancel button for FSM flows."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="admin_cancel", style=ButtonStyle.DANGER)
    builder.adjust(1)
    return builder.as_markup()


def confirm_give_kb(user_id: int, bio: int, premium: int) -> InlineKeyboardMarkup:
    """Confirm currency give operation."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Да",
        callback_data=f"admin_give_confirm_{user_id}_{bio}_{premium}",
        style=ButtonStyle.SUCCESS,
    )
    builder.button(text="❌ Нет", callback_data="admin_cancel", style=ButtonStyle.DANGER)
    builder.adjust(2)
    return builder.as_markup()


# ---------------------------------------------------------------------------
# Events management keyboards
# ---------------------------------------------------------------------------


def admin_events_kb(active_events: list) -> InlineKeyboardMarkup:
    """Events management menu: create button, list of active events, back."""
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Создать ивент", callback_data="admin_event_types", style=ButtonStyle.SUCCESS)
    for event in active_events:
        emoji = EVENT_EMOJI.get(event.event_type, "🌍")
        builder.button(
            text=f"{emoji} {event.title}",
            callback_data=f"admin_evt_detail:{event.id}",
        )
    builder.button(text="◀️ Назад", callback_data="admin_menu")
    builder.adjust(1)
    return builder.as_markup()


def admin_event_types_kb() -> InlineKeyboardMarkup:
    """Select event type to create."""
    builder = InlineKeyboardBuilder()
    type_order = [
        EventType.GOLD_RUSH,
        EventType.ARMS_RACE,
        EventType.PLAGUE_SEASON,
        EventType.IMMUNITY_WAVE,
        EventType.MUTATION_STORM,
        EventType.CEASEFIRE,
        EventType.PANDEMIC,
    ]
    for et in type_order:
        emoji = EVENT_EMOJI[et]
        name = EVENT_NAMES[et]
        builder.button(
            text=f"{emoji} {name}",
            callback_data=f"admin_evt_create:{et.value}",
        )
    builder.button(text="◀️ Назад", callback_data="admin_events")
    builder.adjust(1)
    return builder.as_markup()


def admin_event_duration_kb(event_type: str) -> InlineKeyboardMarkup:
    """Select event duration in hours."""
    builder = InlineKeyboardBuilder()
    durations = [
        ("1 час",    1),
        ("2 часа",   2),
        ("4 часа",   4),
        ("8 часов",  8),
        ("12 часов", 12),
        ("24 часа",  24),
    ]
    for label, hours in durations:
        builder.button(
            text=label,
            callback_data=f"admin_evt_dur:{event_type}:{hours}",
        )
    builder.button(text="◀️ Назад", callback_data="admin_event_types")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()


def admin_event_detail_kb(event_id: int) -> InlineKeyboardMarkup:
    """Active event detail view with stop and back buttons."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🛑 Остановить",
        callback_data=f"admin_evt_stop_ask:{event_id}",
        style=ButtonStyle.DANGER,
    )
    builder.button(text="◀️ Назад", callback_data="admin_events")
    builder.adjust(1)
    return builder.as_markup()


def admin_event_stop_confirm_kb(event_id: int) -> InlineKeyboardMarkup:
    """Confirm stopping an event."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Да, остановить",
        callback_data=f"admin_evt_stop:{event_id}",
        style=ButtonStyle.DANGER,
    )
    builder.button(
        text="❌ Отмена",
        callback_data=f"admin_evt_detail:{event_id}",
    )
    builder.adjust(2)
    return builder.as_markup()


def admin_pandemic_hp_kb(duration: int) -> InlineKeyboardMarkup:
    """Select pandemic boss HP."""
    builder = InlineKeyboardBuilder()
    hp_options = [
        ("5 000 HP",  5_000),
        ("10 000 HP", 10_000),
        ("25 000 HP", 25_000),
        ("50 000 HP", 50_000),
    ]
    for label, hp in hp_options:
        builder.button(
            text=label,
            callback_data=f"admin_pandemic:{duration}:{hp}",
        )
    builder.button(
        text="◀️ Назад",
        callback_data=f"admin_evt_dur:PANDEMIC:{duration}",
    )
    builder.adjust(2, 2, 1)
    return builder.as_markup()
