"""Mutations section keyboard."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.models.mutation import Mutation, MutationRarity, MutationType

# Эмодзи по редкости
RARITY_EMOJI: dict[MutationRarity, str] = {
    MutationRarity.COMMON:    "⚪",
    MutationRarity.UNCOMMON:  "🟢",
    MutationRarity.RARE:      "🔵",
    MutationRarity.LEGENDARY: "🟣",
}

# Русские названия типов мутаций
MUTATION_LABELS: dict[MutationType, str] = {
    MutationType.TOXIC_SPIKE:       "Токсичный шип",
    MutationType.RAPID_SPREAD:      "Быстрое распространение",
    MutationType.PHANTOM_STRAIN:    "Штамм-призрак",
    MutationType.RESOURCE_DRAIN:    "Ресурсный дренаж",
    MutationType.ADAPTIVE_SHELL:    "Адаптивная оболочка",
    MutationType.REGENERATIVE_CORE: "Регенеративное ядро",
    MutationType.DOUBLE_STRIKE:     "Двойной удар",
    MutationType.BIO_MAGNET:        "Биомагнит",
    MutationType.UNSTABLE_CODE:     "Нестабильный код",
    MutationType.IMMUNE_LEAK:       "Иммунная утечка",
    MutationType.SLOW_REPLICATION:  "Медленная репликация",
    MutationType.PLAGUE_BURST:      "Чумной взрыв",
    MutationType.ABSOLUTE_IMMUNITY: "Абсолютный иммунитет",
    MutationType.EVOLUTION_LEAP:    "Эволюционный скачок",
}


def _remaining_text(mutation: Mutation) -> str:
    """Human-readable time remaining for mutation, or special label."""
    if mutation.duration_hours == 0.0:
        return "одноразово" if not mutation.is_used else "использована"
    now = datetime.now(UTC).replace(tzinfo=None)
    expiry = mutation.activated_at + timedelta(hours=mutation.duration_hours)
    remaining = expiry - now
    if remaining.total_seconds() <= 0:
        return "истекла"
    total_seconds = int(remaining.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if hours > 0:
        return f"{hours}ч {minutes}м"
    return f"{minutes}м"


def mutations_menu_kb(mutations: list[Mutation]) -> InlineKeyboardMarkup:
    """
    Display active mutations as informational rows, then a Back button.

    Each mutation gets its own row showing: rarity emoji, name, remaining time.
    Buttons are not interactive (callback just answers the same menu).
    """
    builder = InlineKeyboardBuilder()

    if not mutations:
        builder.button(
            text="— Нет активных мутаций —",
            callback_data="mutations_menu",
        )
    else:
        for m in mutations:
            emoji = RARITY_EMOJI.get(m.rarity, "⚪")
            label = MUTATION_LABELS.get(m.mutation_type, m.mutation_type.value)
            remaining = _remaining_text(m)
            builder.button(
                text=f"{emoji} {label} [{remaining}]",
                callback_data="mutations_menu",
            )

    builder.button(text="◀️ Назад", callback_data="main_menu")
    # One button per row
    builder.adjust(1)
    return builder.as_markup()
