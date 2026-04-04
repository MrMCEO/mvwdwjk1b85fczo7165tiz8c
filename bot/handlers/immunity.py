"""Immunity section handlers — view stats and upgrade branches."""

from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.immunity import immunity_menu_kb, immunity_upgrade_kb
from bot.services.upgrade import get_immunity_stats, upgrade_immunity_branch

router = Router(name="immunity")

# Maps short callback suffix → full branch key
_SHORT_TO_BRANCH = {
    "BAR": "BARRIER",
    "DET": "DETECTION",
    "REG": "REGENERATION",
}


def _fmt_immunity_stats(data: dict) -> str:
    if "error" in data:
        return f"❌ {data['error']}"

    im = data["immunity"]
    upgrades = data["upgrades"]

    lines = [
        "🛡 <b>Мой иммунитет</b>\n",
        f"Уровень: <b>{im['level']}</b>  |  "
        f"Сопротивляемость: <b>{im['resistance']}</b>",
        f"Детекция: <b>{im['detection_power']:.2f}</b>  |  "
        f"Скорость регенерации: <b>{im['recovery_speed']:.2f}</b>",
        "",
        "<b>Ветки прокачки:</b>",
    ]

    icons = {"BARRIER": "🛡", "DETECTION": "🔍", "REGENERATION": "💊"}
    for branch_key, info in upgrades.items():
        icon = icons.get(branch_key, "•")
        next_cost = info.get("next_cost")
        cost_text = "МАКС" if next_cost is None else f"→ след. уровень <b>{next_cost}</b> bio"
        lines.append(
            f"  {icon} {info['name']}: ур. <b>{info['level']}</b>  "
            f"(эффект {info['effect_value']:.2f})  "
            f"{cost_text}"
        )

    return "\n".join(lines)


@router.callback_query(lambda c: c.data == "immunity_menu")
async def cb_immunity_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    data = await get_immunity_stats(session, callback.from_user.id)
    text = _fmt_immunity_stats(data)
    upgrades = data.get("upgrades")
    await callback.message.edit_text(
        text, reply_markup=immunity_menu_kb(upgrades), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("upg_i_"))
async def cb_upgrade_immunity(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show confirmation keyboard for a specific immunity branch upgrade."""
    short = callback.data[6:].upper()  # e.g. "BAR"
    branch = _SHORT_TO_BRANCH.get(short)
    if not branch:
        await callback.answer("Неизвестная ветка.", show_alert=True)
        return

    data = await get_immunity_stats(session, callback.from_user.id)
    if "error" in data:
        await callback.answer(data["error"], show_alert=True)
        return

    upgrades = data.get("upgrades", {})
    info = upgrades.get(branch, {})
    branch_name = info.get("name", branch)
    current_level = info.get("level", 0)
    cost = info.get("next_cost")  # None means max level

    if cost is None:
        await callback.answer(
            f"Ветка «{branch_name}» уже на максимальном уровне!", show_alert=True
        )
        return

    text = (
        f"🔬 <b>Прокачать ветку «{branch_name}»</b>\n\n"
        f"Текущий уровень: <b>{current_level}</b>\n"
        f"Следующий уровень: <b>{current_level + 1}</b>\n"
        f"Стоимость: <b>{cost}</b> bio_coins\n\n"
        "Подтвердить прокачку?"
    )
    await callback.message.edit_text(
        text, reply_markup=immunity_upgrade_kb(branch), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("conf_upg_i_"))
async def cb_confirm_upgrade_immunity(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Execute the immunity branch upgrade after confirmation."""
    short = callback.data[11:].upper()  # after "conf_upg_i_"
    branch = _SHORT_TO_BRANCH.get(short)
    if not branch:
        await callback.answer("Неизвестная ветка.", show_alert=True)
        return

    success, message = await upgrade_immunity_branch(
        session, callback.from_user.id, branch
    )

    if not success:
        await callback.answer(message, show_alert=True)
        return

    # Re-fetch and show updated stats
    data = await get_immunity_stats(session, callback.from_user.id)
    text = _fmt_immunity_stats(data)
    upgrades = data.get("upgrades")
    await callback.message.edit_text(
        f"✅ {message}\n\n" + text,
        reply_markup=immunity_menu_kb(upgrades),
        parse_mode="HTML",
    )
    await callback.answer("Прокачано!")
