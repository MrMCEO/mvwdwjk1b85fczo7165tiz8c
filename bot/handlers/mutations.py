"""Mutations section handler — view active virus mutations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.mutations import (
    MUTATION_LABELS,
    RARITY_EMOJI,
    mutations_menu_kb,
)
from bot.models.mutation import Mutation, MutationRarity, MutationType
from bot.services.mutation import MUTATION_CONFIG, get_active_mutations

router = Router(name="mutations")

# Описания бонусов по типу (для текстового вывода)
_EFFECT_SIGN: dict[MutationType, str] = {
    MutationType.UNSTABLE_CODE:    "−",
    MutationType.IMMUNE_LEAK:      "−",
    MutationType.SLOW_REPLICATION: "−",
}

_RARITY_LABELS: dict[MutationRarity, str] = {
    MutationRarity.COMMON:    "Обычная",
    MutationRarity.UNCOMMON:  "Необычная",
    MutationRarity.RARE:      "Редкая",
    MutationRarity.LEGENDARY: "Легендарная",
}


def _remaining_text(mutation: Mutation) -> str:
    """Human-readable time remaining."""
    if mutation.duration_hours == 0.0:
        return "одноразово"
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


def _fmt_mutations_text(mutations: list[Mutation]) -> str:
    lines = ["🧬 <b>Активные мутации вируса</b>\n"]

    if not mutations:
        lines.append("У тебя нет активных мутаций.")
        lines.append("")
        lines.append(
            "Мутации выпадают случайно после атак (шанс 15%).\n"
            "Они дают временные баффы или дебаффы твоему вирусу."
        )
        return "\n".join(lines)

    for m in mutations:
        emoji = RARITY_EMOJI.get(m.rarity, "⚪")
        name = MUTATION_LABELS.get(m.mutation_type, m.mutation_type.value)
        rarity_label = _RARITY_LABELS.get(m.rarity, m.rarity.value)
        cfg = MUTATION_CONFIG.get(m.mutation_type, {})
        description = cfg.get("description", "")
        remaining = _remaining_text(m)

        lines.append(
            f"{emoji} <b>{name}</b> [{rarity_label}]\n"
            f"   {description} — осталось: <b>{remaining}</b>"
        )

    lines.append("")
    lines.append(
        f"Всего активных мутаций: <b>{len(mutations)}</b>"
    )
    return "\n".join(lines)


@router.callback_query(lambda c: c.data == "mutations_menu")
async def cb_mutations_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    user_id = callback.from_user.id
    active_mutations = await get_active_mutations(session, user_id)
    text = _fmt_mutations_text(active_mutations)
    await callback.message.edit_text(
        text,
        reply_markup=mutations_menu_kb(active_mutations),
        parse_mode="HTML",
    )
    await callback.answer()
