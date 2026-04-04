"""
Premium subscription handlers.

Callbacks:
  premium_menu       — show subscription info / perks description
  premium_buy        — show confirmation prompt
  premium_confirm    — finalize purchase
  premium_set_prefix — FSM: enter custom prefix
"""

from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.premium import premium_confirm_kb, premium_menu_kb
from bot.services.premium import (
    PREFIX_MAX_CHARS,
    buy_premium,
    clear_prefix,
    get_prefix,
    get_premium_info,
    set_prefix,
)

router = Router(name="premium")


class PrefixStates(StatesGroup):
    waiting_for_prefix = State()

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
    "🏷 Кастомный префикс в профиле и рейтингах (до 5 символов)"
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


# ---------------------------------------------------------------------------
# Premium prefix — FSM
# ---------------------------------------------------------------------------


def _prefix_enter_kb() -> None:
    """Keyboard with a cancel button for prefix input."""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="premium_prefix_cancel")
    builder.adjust(1)
    return builder.as_markup()


@router.callback_query(lambda c: c.data == "premium_set_prefix")
async def cb_set_prefix_enter(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Prompt the user to type a new prefix."""
    info = await get_premium_info(session, callback.from_user.id)
    if not info["is_active"]:
        await callback.answer(
            "❌ Кастомный префикс доступен только для премиум-подписчиков.",
            show_alert=True,
        )
        return

    current = await get_prefix(session, callback.from_user.id)
    current_line = f"\nТекущий префикс: <b>[{current}]</b>" if current else ""

    await state.set_state(PrefixStates.waiting_for_prefix)
    await callback.message.edit_text(
        f"✏️ <b>Установить кастомный префикс</b>\n\n"
        f"Введи префикс до {PREFIX_MAX_CHARS} символов. Он будет отображаться "
        f"рядом с твоим именем в профиле, рейтингах и при атаках.\n\n"
        f"Примеры: <code>[VIP]</code>, <code>[PRO]</code>, <code>[💀]</code>, "
        f"<code>[ТОП]</code>{current_line}\n\n"
        f"Или нажми «Отмена» чтобы вернуться назад:",
        reply_markup=_prefix_enter_kb(),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "premium_prefix_cancel")
async def cb_prefix_cancel(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Cancel prefix input and return to premium menu."""
    await state.clear()
    info = await get_premium_info(session, callback.from_user.id)
    text = _fmt_premium_menu(info)
    await callback.message.edit_text(
        text,
        reply_markup=premium_menu_kb(info["is_active"]),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "premium_prefix_clear")
async def cb_prefix_clear(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Reset prefix to the default ⭐."""
    await state.clear()
    success, message = await clear_prefix(session, callback.from_user.id)
    info = await get_premium_info(session, callback.from_user.id)
    text = f"{message}\n\n" + _fmt_premium_menu(info)
    await callback.message.edit_text(
        text,
        reply_markup=premium_menu_kb(info["is_active"]),
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(PrefixStates.waiting_for_prefix)
async def msg_prefix_input(
    message: Message, state: FSMContext, session: AsyncSession
) -> None:
    """Process the prefix text entered by the user."""
    raw = (message.text or "").strip()

    success, result_msg = await set_prefix(session, message.from_user.id, raw)

    await state.clear()

    if not success:
        await message.answer(
            result_msg,
            reply_markup=_prefix_enter_kb(),
            parse_mode="HTML",
        )
        # Re-enter the FSM state so the user can try again
        await state.set_state(PrefixStates.waiting_for_prefix)
        return

    info = await get_premium_info(session, message.from_user.id)
    text = f"{result_msg}\n\n" + _fmt_premium_menu(info)
    await message.answer(
        text,
        reply_markup=premium_menu_kb(info["is_active"]),
        parse_mode="HTML",
    )
