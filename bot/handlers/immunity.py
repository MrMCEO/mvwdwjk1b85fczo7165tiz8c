"""Immunity section handlers — view stats and upgrade branches."""

from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.immunity import immunity_menu_kb
from bot.services.upgrade import get_immunity_stats, upgrade_immunity_branch
from bot.utils.chat import dlvl
from bot.utils.throttle import check_throttle

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
        f"⭐ Уровень: <code>{dlvl(im['level'])}</code>",
        f"🔰 Сопротивляемость: <code>{im['resistance']}</code>  │  "
        f"🔍 Детекция: <code>{im['detection_power']:.2f}</code>",
        "",
        "━━━━━━━━━━━━━━━",
        "<b>Ветки прокачки:</b>",
    ]

    icons = {"BARRIER": "🛡", "DETECTION": "🔍", "REGENERATION": "💊"}
    for branch_key, info in upgrades.items():
        icon = icons.get(branch_key, "•")
        next_cost = info.get("next_cost")
        cost_text = "<i>макс.</i>" if next_cost is None else f"<code>{next_cost}</code> 🧫"
        lines.append(
            f"{icon} {info['name']}: ур. <code>{dlvl(info['level'])}</code>  │  {cost_text}"
        )

    lines += ["", "<i>Нажми кнопку ниже для прокачки ветки</i>"]
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
    """Upgrade immunity branch immediately on button press."""
    remaining = check_throttle(callback.from_user.id, "upgrade_immunity")
    if remaining > 0:
        await callback.answer(f"Повторите попытку через {remaining:.0f} сек.", show_alert=True)
        return

    short = callback.data[6:].upper()
    branch = _SHORT_TO_BRANCH.get(short)
    if not branch:
        await callback.answer("Неизвестная ветка.", show_alert=True)
        return

    # Acknowledge immediately to prevent query timeout
    await callback.answer()

    success, message = await upgrade_immunity_branch(
        session, callback.from_user.id, branch
    )

    if not success:
        await callback.message.edit_text(
            f"❌ {message}",
            reply_markup=immunity_menu_kb(None),
            parse_mode="HTML",
        )
        return

    data = await get_immunity_stats(session, callback.from_user.id)
    text = _fmt_immunity_stats(data)
    upgrades = data.get("upgrades")
    await callback.message.edit_text(
        f"✅ {message}\n\n" + text,
        reply_markup=immunity_menu_kb(upgrades),
        parse_mode="HTML",
    )
