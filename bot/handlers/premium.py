"""
Premium subscription handlers.

Callbacks:
  premium_menu    — show subscription info / perks description
  premium_buy     — show confirmation prompt
  premium_confirm — finalize purchase
"""

from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.premium import premium_confirm_kb, premium_menu_kb
from bot.services.premium import buy_premium, get_premium_info

router = Router(name="premium")

# ---------------------------------------------------------------------------
# Text constants
# ---------------------------------------------------------------------------

PERKS_TEXT = (
    "⭐ <b>Премиум-подписка</b> — 200 💎/мес\n\n"
    "<b>Преимущества:</b>\n"
    "🧫 +25% к добыче ресурсов\n"
    "🎁 +50% к ежедневному бонусу\n"
    "⏱ Кулдаун добычи: 45 мин (вместо 60)\n"
    "⚔️ Кулдаун атаки: 25 мин (вместо 30)\n"
    "🎯 4 попытки на цель/час (вместо 3)\n"
    "🦠 6 заражений/час (вместо 5)\n"
    "✏️ Имя вируса до 30 символов\n"
    "⭐ Премиум эмодзи в имени вируса\n"
    "🏆 Бейдж ⭐ в профиле и рейтинге"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_premium_menu(info: dict) -> str:
    """Format the premium menu text based on subscription status."""
    if info["is_active"]:
        until_str = info["until"].strftime("%d.%m.%Y")
        days = info["days_left"]
        status_line = (
            f"✅ <b>Премиум активен</b> до {until_str} ({days} дн.)\n\n"
        )
        return status_line + PERKS_TEXT
    else:
        return PERKS_TEXT


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "premium_menu")
async def cb_premium_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show premium subscription info and perks."""
    info = await get_premium_info(session, callback.from_user.id)
    text = _fmt_premium_menu(info)
    await callback.message.edit_text(
        text,
        reply_markup=premium_menu_kb(info["is_active"]),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "premium_buy")
async def cb_premium_buy(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show confirmation prompt before charging the user."""
    info = await get_premium_info(session, callback.from_user.id)
    action = "продлить" if info["is_active"] else "купить"
    await callback.message.edit_text(
        f"⭐ <b>Подтверждение покупки</b>\n\n"
        f"Вы хотите {action} Премиум-подписку на 30 дней за <b>200 💎</b> PremiumCoins.\n\n"
        "Подтвердить?",
        reply_markup=premium_confirm_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "premium_confirm")
async def cb_premium_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    """Finalise premium purchase."""
    success, message = await buy_premium(session, callback.from_user.id)

    if not success:
        await callback.answer(message, show_alert=True)
        return

    # Reload info to show updated status
    info = await get_premium_info(session, callback.from_user.id)
    text = f"✅ {message}\n\n" + _fmt_premium_menu(info)
    await callback.message.edit_text(
        text,
        reply_markup=premium_menu_kb(info["is_active"]),
        parse_mode="HTML",
    )
    await callback.answer("⭐ Подписка активирована!")
