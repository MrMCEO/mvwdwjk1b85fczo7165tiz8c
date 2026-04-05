"""
Premium / status system handlers.

Callbacks:
  premium_menu           — show status info & all available statuses
  status_buy:<STATUS>    — show purchase confirmation
  status_confirm:<STATUS> — finalise purchase
  status_legend_info     — popup explaining BIO_LEGEND requirements
  premium_set_prefix     — FSM: enter custom prefix
  premium_prefix_cancel  — cancel prefix input
  premium_prefix_clear   — reset prefix
"""

from __future__ import annotations

from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.premium import status_confirm_kb, status_menu_kb
from bot.utils.chat import smart_reply
from bot.services.premium import (
    STATUS_CONFIG,
    UserStatus,
    buy_status,
    clear_prefix,
    get_prefix,
    get_premium_info,
    get_user_status,
    set_prefix,
)

router = Router(name="premium")


class PrefixStates(StatesGroup):
    waiting_for_prefix = State()


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def _fmt_status_line(info: dict) -> str:
    """Return a one-liner describing the user's current status."""
    status: UserStatus = info["status"]
    cfg = STATUS_CONFIG[status]
    emoji = cfg["emoji"]
    name = cfg["name"]

    if not info["is_active"]:
        return f"Ваш статус: {name}"

    if status in (UserStatus.BIO_LEGEND, UserStatus.OWNER):
        return f"Ваш статус: {emoji} {name} (навсегда)"

    until = info["until"]
    until_str = until.strftime("%d.%m.%Y") if until else "∞"
    return f"Ваш статус: {emoji} {name} (до {until_str})"


def _fmt_status_list() -> str:
    """Build the readable list of all statuses with prices."""
    lines: list[str] = []
    for s, cfg in STATUS_CONFIG.items():
        emoji = cfg["emoji"]
        name = cfg["name"]
        price = cfg["price"]
        if s in (UserStatus.FREE, UserStatus.OWNER):
            continue
        if s == UserStatus.BIO_LEGEND:
            lines.append(f"{emoji} {name} — только через рефералов (50+)")
        else:
            lines.append(f"{emoji} {name} — {price} 💎/мес")
    return "\n".join(lines)


def _fmt_premium_menu(info: dict) -> str:
    """Format the full status menu message."""
    status_line = _fmt_status_line(info)
    statuses_block = _fmt_status_list()
    return (
        "📊 <b>Система статусов</b>\n\n"
        f"{status_line}\n\n"
        "<b>Доступные статусы:</b>\n"
        f"{statuses_block}"
    )


def _fmt_perks(status: UserStatus) -> str:
    """Return a short perks description for *status*."""
    cfg = STATUS_CONFIG[status]
    lines = [
        f"🧫 +{int(cfg['mining_bonus'] * 100)}% к добыче ресурсов",
        f"🎁 +{int(cfg['daily_bonus'] * 100)}% к ежедневному бонусу",
        f"⏱ Кулдаун добычи: {cfg['mining_cooldown']} мин",
        f"⚔️ Кулдаун атаки: {cfg['attack_cooldown']} мин",
        f"🎯 {cfg['max_attempts_target']} попытки на цель/час",
        f"🦠 {cfg['max_infections_hour']} заражений/час",
        f"💸 Лимит перевода: {cfg['transfer_limit']} 🧬",
        f"✏️ Префикс до {cfg['prefix_length']} символов" if cfg["prefix_length"] else "❌ Без префикса",
        f"⭐ Премиум-эмодзи в вирусах: {'да' if cfg['premium_emoji'] else 'нет'}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "premium_menu")
async def cb_premium_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show status overview with all available tiers."""
    user_id = callback.from_user.id
    info = await get_premium_info(session, user_id)
    status = info["status"]

    text = _fmt_premium_menu(info)
    await callback.message.edit_text(
        text,
        reply_markup=status_menu_kb(current_status=status),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("status_buy:"))
async def cb_status_buy(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show purchase confirmation for the selected status."""
    raw = callback.data.split(":", 1)[1]
    try:
        target = UserStatus(raw)
    except ValueError:
        await callback.answer("Неизвестный статус.", show_alert=True)
        return

    if target in (UserStatus.FREE, UserStatus.BIO_LEGEND):
        await callback.answer(
            "Этот статус нельзя купить — он выдаётся автоматически.",
            show_alert=True,
        )
        return

    cfg = STATUS_CONFIG[target]
    perks = _fmt_perks(target)
    text = (
        f"{cfg['emoji']} <b>Подтверждение покупки — {cfg['name']}</b>\n\n"
        f"Стоимость: <b>{cfg['price']} 💎</b> PremiumCoins / мес\n\n"
        f"<b>Перки:</b>\n{perks}\n\n"
        "Подтвердить покупку?"
    )
    await callback.message.edit_text(
        text,
        reply_markup=status_confirm_kb(target),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data and c.data.startswith("status_confirm:"))
async def cb_status_confirm(callback: CallbackQuery, session: AsyncSession) -> None:
    """Finalise status purchase."""
    raw = callback.data.split(":", 1)[1]
    try:
        target = UserStatus(raw)
    except ValueError:
        await callback.answer("Неизвестный статус.", show_alert=True)
        return

    success, message = await buy_status(session, callback.from_user.id, target)

    if not success:
        await callback.answer(message, show_alert=True)
        return

    info = await get_premium_info(session, callback.from_user.id)
    text = f"✅ {message}\n\n" + _fmt_premium_menu(info)
    await callback.message.edit_text(
        text,
        reply_markup=status_menu_kb(current_status=info["status"]),
        parse_mode="HTML",
    )
    cfg = STATUS_CONFIG[target]
    await callback.answer(f"{cfg['emoji']} Статус {cfg['name']} активирован!")


@router.callback_query(lambda c: c.data == "status_legend_info")
async def cb_legend_info(callback: CallbackQuery) -> None:
    """Popup explaining how to get BIO_LEGEND."""
    await callback.answer(
        "👑 Bio Legend выдаётся автоматически при достижении 50+ рефералов.",
        show_alert=True,
    )


# ---------------------------------------------------------------------------
# Prefix — FSM
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
    status = await get_user_status(session, callback.from_user.id)
    allowed_len = STATUS_CONFIG[status]["prefix_length"]

    if allowed_len == 0:
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
        f"Введи префикс до <b>{allowed_len}</b> символов. Он будет отображаться "
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
    """Cancel prefix input and return to status menu."""
    await state.clear()
    info = await get_premium_info(session, callback.from_user.id)
    text = _fmt_premium_menu(info)
    await callback.message.edit_text(
        text,
        reply_markup=status_menu_kb(current_status=info["status"]),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(lambda c: c.data == "premium_prefix_clear")
async def cb_prefix_clear(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession
) -> None:
    """Reset prefix."""
    await state.clear()
    success, message = await clear_prefix(session, callback.from_user.id)
    info = await get_premium_info(session, callback.from_user.id)
    text = f"{message}\n\n" + _fmt_premium_menu(info)
    await callback.message.edit_text(
        text,
        reply_markup=status_menu_kb(current_status=info["status"]),
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
        await smart_reply(
            message,
            result_msg,
            reply_markup=_prefix_enter_kb(),
        )
        await state.set_state(PrefixStates.waiting_for_prefix)
        return

    info = await get_premium_info(session, message.from_user.id)
    text = f"{result_msg}\n\n" + _fmt_premium_menu(info)
    await smart_reply(
        message,
        text,
        reply_markup=status_menu_kb(current_status=info["status"]),
    )
