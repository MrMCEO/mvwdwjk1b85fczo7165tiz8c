"""User /suggest command + admin moderation callbacks."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.models.suggestion import Suggestion, SuggestBlock, SuggestionStatus
from bot.utils.db_logger import log_event

logger = logging.getLogger(__name__)
router = Router(name="suggest")

RATE_LIMIT_COUNT = 5
RATE_LIMIT_WINDOW_MIN = 30
MIN_LENGTH = 10
MAX_LENGTH = 1000


def _moderation_kb(suggestion_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Одобрить", callback_data=f"sug_ok_{suggestion_id}")
    builder.button(text="❌ Отклонить", callback_data=f"sug_no_{suggestion_id}")
    builder.button(text="🚫 Заблокировать", callback_data=f"sug_bl_{suggestion_id}")
    builder.adjust(2, 1)
    return builder.as_markup()


@router.message(Command("suggest"))
async def cmd_suggest(message: Message, session: AsyncSession, command: CommandObject, bot: Bot) -> None:
    """Handle /suggest <text> command from users."""
    user_id = message.from_user.id
    username = message.from_user.username or ""

    # Check block
    blocked = await session.execute(
        select(SuggestBlock).where(SuggestBlock.user_id == user_id)
    )
    if blocked.scalar_one_or_none() is not None:
        await message.reply("🚫 Вы заблокированы от отправки предложений.")
        return

    # Validate text
    text = (command.args or "").strip()
    if not text:
        await message.reply(
            "💡 <b>Отправка предложения</b>\n\n"
            "Используй: <code>/suggest &lt;твой текст&gt;</code>\n\n"
            f"Текст должен быть от {MIN_LENGTH} до {MAX_LENGTH} символов.",
            parse_mode="HTML",
        )
        return
    if len(text) < MIN_LENGTH:
        await message.reply(f"❌ Слишком короткое предложение. Минимум {MIN_LENGTH} символов.")
        return
    if len(text) > MAX_LENGTH:
        await message.reply(f"❌ Слишком длинное предложение. Максимум {MAX_LENGTH} символов.")
        return

    # Rate limit: count in last RATE_LIMIT_WINDOW_MIN minutes
    window_start = datetime.utcnow() - timedelta(minutes=RATE_LIMIT_WINDOW_MIN)
    count_result = await session.execute(
        select(func.count(Suggestion.id))
        .where(Suggestion.user_id == user_id)
        .where(Suggestion.created_at >= window_start)
    )
    recent_count = count_result.scalar_one()
    if recent_count >= RATE_LIMIT_COUNT:
        await message.reply(
            f"⏳ Лимит предложений: {RATE_LIMIT_COUNT} за {RATE_LIMIT_WINDOW_MIN} минут. "
            "Подожди немного."
        )
        return

    # Create suggestion
    suggestion = Suggestion(
        user_id=user_id,
        username=username,
        text=text,
        status=SuggestionStatus.PENDING,
    )
    session.add(suggestion)
    await session.flush()  # get suggestion.id

    # Log event
    await log_event(
        session,
        event_type="suggestion",
        user_id=user_id,
        message=f"New suggestion from {username}: {text[:80]}",
        extra={"suggestion_id": suggestion.id, "length": len(text)},
    )

    # Notify admins via DM
    settings = get_settings()
    kb = _moderation_kb(suggestion.id)
    display_user = f"@{escape(username)}" if username else f"id{user_id}"
    admin_text = (
        f"💡 <b>Новое предложение</b> #{suggestion.id}\n\n"
        f"От: {display_user} (<code>{user_id}</code>)\n\n"
        f"<i>{escape(text)}</i>"
    )
    for admin_id in settings.admin_ids:
        try:
            await bot.send_message(admin_id, admin_text, reply_markup=kb, parse_mode="HTML")
        except Exception as exc:
            logger.warning(f"Failed to notify admin {admin_id}: {exc}")

    await message.reply("✅ Спасибо! Твоё предложение отправлено на рассмотрение.")


def _is_admin(user_id: int) -> bool:
    return user_id in get_settings().admin_ids


@router.callback_query(F.data.startswith("sug_ok_"))
async def cb_approve(callback: CallbackQuery, session: AsyncSession, bot: Bot) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Только для админа.", show_alert=True)
        return
    await callback.answer()
    suggestion_id = int(callback.data.split("_")[-1])
    result = await session.execute(select(Suggestion).where(Suggestion.id == suggestion_id))
    suggestion = result.scalar_one_or_none()
    if suggestion is None:
        await callback.message.edit_text("❌ Предложение не найдено.")
        return
    suggestion.status = SuggestionStatus.APPROVED
    suggestion.moderated_at = datetime.utcnow()
    suggestion.moderated_by = callback.from_user.id
    await log_event(
        session,
        event_type="suggestion_approved",
        user_id=suggestion.user_id,
        message=f"Suggestion #{suggestion.id} approved",
        extra={"suggestion_id": suggestion.id, "approved_by": callback.from_user.id},
    )
    # Notify the user
    try:
        await bot.send_message(
            suggestion.user_id,
            f"✅ <b>Твоё предложение одобрено!</b>\n\n<i>{escape(suggestion.text)}</i>",
            parse_mode="HTML",
        )
    except Exception as exc:
        logger.debug(f"Failed to notify user {suggestion.user_id} about approval: {exc}")
    # Edit admin's message
    await callback.message.edit_text(
        f"✅ <b>Предложение #{suggestion.id} одобрено</b>\n\n<i>{escape(suggestion.text)}</i>",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("sug_no_"))
async def cb_reject(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Только для админа.", show_alert=True)
        return
    await callback.answer()
    suggestion_id = int(callback.data.split("_")[-1])
    result = await session.execute(select(Suggestion).where(Suggestion.id == suggestion_id))
    suggestion = result.scalar_one_or_none()
    if suggestion is None:
        await callback.message.edit_text("❌ Предложение не найдено.")
        return
    suggestion.status = SuggestionStatus.REJECTED
    suggestion.moderated_at = datetime.utcnow()
    suggestion.moderated_by = callback.from_user.id
    await log_event(
        session,
        event_type="suggestion_rejected",
        user_id=suggestion.user_id,
        message=f"Suggestion #{suggestion.id} rejected",
        extra={"suggestion_id": suggestion.id, "rejected_by": callback.from_user.id},
    )
    await callback.message.edit_text(
        f"❌ <b>Предложение #{suggestion.id} отклонено</b>\n\n<i>{escape(suggestion.text)}</i>",
        parse_mode="HTML",
    )


@router.callback_query(F.data.startswith("sug_bl_"))
async def cb_block(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Только для админа.", show_alert=True)
        return
    await callback.answer()
    suggestion_id = int(callback.data.split("_")[-1])
    result = await session.execute(select(Suggestion).where(Suggestion.id == suggestion_id))
    suggestion = result.scalar_one_or_none()
    if suggestion is None:
        await callback.message.edit_text("❌ Предложение не найдено.")
        return
    # Reject the current suggestion and block the user
    suggestion.status = SuggestionStatus.REJECTED
    suggestion.moderated_at = datetime.utcnow()
    suggestion.moderated_by = callback.from_user.id
    # Add block if not already present
    existing = await session.execute(
        select(SuggestBlock).where(SuggestBlock.user_id == suggestion.user_id)
    )
    if existing.scalar_one_or_none() is None:
        block = SuggestBlock(user_id=suggestion.user_id, blocked_by=callback.from_user.id)
        session.add(block)
    await log_event(
        session,
        event_type="suggestion_blocked",
        user_id=suggestion.user_id,
        message=f"User {suggestion.user_id} blocked from suggestions",
        extra={"blocked_by": callback.from_user.id, "via_suggestion": suggestion.id},
    )
    await callback.message.edit_text(
        f"🚫 <b>Пользователь заблокирован</b>\n\n"
        f"Предложение #{suggestion.id} от <code>{suggestion.user_id}</code>\n"
        f"<i>{escape(suggestion.text)}</i>",
        parse_mode="HTML",
    )
