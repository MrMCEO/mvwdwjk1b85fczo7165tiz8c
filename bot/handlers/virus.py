"""Virus section handlers — view stats and upgrade branches."""

from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.virus import virus_menu_kb, virus_upgrade_kb
from bot.services.upgrade import get_virus_stats, upgrade_virus_branch

router = Router(name="virus")

# Maps short callback suffix → full branch key
_SHORT_TO_BRANCH = {
    "LET": "LETHALITY",
    "CON": "CONTAGION",
    "STE": "STEALTH",
}


def _fmt_virus_stats(data: dict) -> str:
    if "error" in data:
        return f"❌ {data['error']}"

    v = data["virus"]
    upgrades = data["upgrades"]

    lines = [
        "🦠 <b>Мой вирус</b>\n",
        f"Название: <b>{v['name']}</b>  |  Уровень: <b>{v['level']}</b>",
        f"Сила атаки: <b>{v['attack_power']}</b>  |  "
        f"Заразность: <b>{v['spread_rate']:.2f}</b>",
        f"Очки мутации: <b>{v['mutation_points']}</b>",
        "",
        "<b>Ветки прокачки:</b>",
    ]

    icons = {"LETHALITY": "☠️", "CONTAGION": "🦠", "STEALTH": "👁"}
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


@router.callback_query(lambda c: c.data == "virus_menu")
async def cb_virus_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    data = await get_virus_stats(session, callback.from_user.id)
    text = _fmt_virus_stats(data)
    upgrades = data.get("upgrades")
    await callback.message.edit_text(
        text, reply_markup=virus_menu_kb(upgrades), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("upg_v_"))
async def cb_upgrade_virus(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show confirmation keyboard for a specific virus branch upgrade."""
    short = callback.data[6:].upper()  # e.g. "LET"
    branch = _SHORT_TO_BRANCH.get(short)
    if not branch:
        await callback.answer("Неизвестная ветка.", show_alert=True)
        return

    data = await get_virus_stats(session, callback.from_user.id)
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
        text, reply_markup=virus_upgrade_kb(branch), parse_mode="HTML"
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("conf_upg_v_"))
async def cb_confirm_upgrade_virus(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Execute the virus branch upgrade after confirmation."""
    short = callback.data[11:].upper()  # after "conf_upg_v_"
    branch = _SHORT_TO_BRANCH.get(short)
    if not branch:
        await callback.answer("Неизвестная ветка.", show_alert=True)
        return

    success, message = await upgrade_virus_branch(session, callback.from_user.id, branch)

    if not success:
        await callback.answer(message, show_alert=True)
        return

    # Re-fetch and show updated stats
    data = await get_virus_stats(session, callback.from_user.id)
    text = _fmt_virus_stats(data)
    upgrades = data.get("upgrades")
    await callback.message.edit_text(
        f"✅ {message}\n\n" + text,
        reply_markup=virus_menu_kb(upgrades),
        parse_mode="HTML",
    )
    await callback.answer("Прокачано!")
