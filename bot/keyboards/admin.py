"""Admin panel keyboards."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def admin_menu_kb() -> InlineKeyboardMarkup:
    """Main admin panel navigation keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Промокоды",    callback_data="admin_promos")
    builder.button(text="🔍 Найти игрока", callback_data="admin_find_player")
    builder.button(text="💰 Выдать валюту", callback_data="admin_give_start")
    builder.button(text="📊 Статистика",   callback_data="admin_stats")
    builder.adjust(2, 2)
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
        builder.button(text="🗑 Деактивировать", callback_data=f"admin_promo_del_{code}")
    builder.button(text="🔙 Промокоды", callback_data="admin_promos")
    builder.adjust(1)
    return builder.as_markup()


def admin_player_kb(user_id: int) -> InlineKeyboardMarkup:
    """Per-player action keyboard."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Логи прокачки",     callback_data=f"admin_logs_{user_id}_upgrades")
    builder.button(text="⚔️ Логи атак",         callback_data=f"admin_logs_{user_id}_attacks")
    builder.button(text="💰 Логи транзакций",   callback_data=f"admin_logs_{user_id}_purchases")
    builder.button(text="💵 Выдать валюту",      callback_data=f"admin_give_{user_id}")
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
    builder.button(text="❌ Отмена", callback_data="admin_cancel")
    builder.adjust(1)
    return builder.as_markup()


def confirm_give_kb(user_id: int, bio: int, premium: int) -> InlineKeyboardMarkup:
    """Confirm currency give operation."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✅ Да",
        callback_data=f"admin_give_confirm_{user_id}_{bio}_{premium}",
    )
    builder.button(text="❌ Нет", callback_data="admin_cancel")
    builder.adjust(2)
    return builder.as_markup()
