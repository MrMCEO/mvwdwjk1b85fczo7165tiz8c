"""Admin broadcast feature — send messages to all known chats."""
from __future__ import annotations

import asyncio
import logging
from html import escape

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, MessageEntity
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import get_settings
from bot.models.known_chat import KnownChat

logger = logging.getLogger(__name__)
router = Router(name="broadcast")


class BroadcastStates(StatesGroup):
    choosing_targets = State()
    waiting_for_text = State()
    waiting_for_confirm = State()


def _is_admin(user_id: int) -> bool:
    return user_id in get_settings().admin_ids


def _target_kb(dm_selected: bool, groups_selected: bool) -> "InlineKeyboardMarkup":
    builder = InlineKeyboardBuilder()
    dm_mark = "✅" if dm_selected else "⬜"
    group_mark = "✅" if groups_selected else "⬜"
    builder.button(text=f"{dm_mark} Личные чаты", callback_data="bcast_tgl_dm")
    builder.button(text=f"{group_mark} Группы", callback_data="bcast_tgl_gr")
    if dm_selected or groups_selected:
        builder.button(text="▶️ Далее", callback_data="bcast_next")
    builder.button(text="❌ Отмена", callback_data="bcast_cancel")
    builder.adjust(1, 1, 1, 1)
    return builder.as_markup()


def _confirm_kb() -> "InlineKeyboardMarkup":
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить", callback_data="bcast_send")
    builder.button(text="❌ Отмена", callback_data="bcast_cancel")
    builder.adjust(2)
    return builder.as_markup()


@router.callback_query(F.data == "admin_broadcast")
async def cb_broadcast_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        await callback.answer("Только для админа.", show_alert=True)
        return
    await callback.answer()
    await state.set_state(BroadcastStates.choosing_targets)
    await state.update_data(dm=False, groups=False)
    await callback.message.edit_text(
        "📢 <b>Рассылка</b>\n\nВыбери куда отправить сообщение:",
        reply_markup=_target_kb(False, False),
        parse_mode="HTML",
    )


@router.callback_query(BroadcastStates.choosing_targets, F.data == "bcast_tgl_dm")
async def cb_toggle_dm(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    dm = not data.get("dm", False)
    groups = data.get("groups", False)
    await state.update_data(dm=dm, groups=groups)
    await callback.message.edit_reply_markup(reply_markup=_target_kb(dm, groups))


@router.callback_query(BroadcastStates.choosing_targets, F.data == "bcast_tgl_gr")
async def cb_toggle_groups(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    groups = not data.get("groups", False)
    dm = data.get("dm", False)
    await state.update_data(dm=dm, groups=groups)
    await callback.message.edit_reply_markup(reply_markup=_target_kb(dm, groups))


@router.callback_query(BroadcastStates.choosing_targets, F.data == "bcast_next")
async def cb_targets_next(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    data = await state.get_data()
    if not (data.get("dm") or data.get("groups")):
        await callback.answer("Выбери хотя бы один тип.", show_alert=True)
        return
    await state.set_state(BroadcastStates.waiting_for_text)
    await callback.message.edit_text(
        "📢 <b>Рассылка</b>\n\nОтправь текст сообщения следующим сообщением.\n"
        "Поддерживаются форматирование и premium-эмодзи.",
        parse_mode="HTML",
    )


@router.message(BroadcastStates.waiting_for_text)
async def msg_broadcast_text(message: Message, state: FSMContext) -> None:
    text = message.text or message.caption or ""
    if not text.strip():
        await message.reply("❌ Пустое сообщение. Отправь текст.")
        return
    # Store text + entities for later rebroadcast
    entities = message.entities or message.caption_entities or []
    entities_data = [
        {
            "type": e.type,
            "offset": e.offset,
            "length": e.length,
            "url": getattr(e, "url", None),
            "user": None,  # we don't broadcast user mentions
            "language": getattr(e, "language", None),
            "custom_emoji_id": getattr(e, "custom_emoji_id", None),
        }
        for e in entities
    ]
    await state.update_data(text=text, entities=entities_data)
    await state.set_state(BroadcastStates.waiting_for_confirm)

    data = await state.get_data()
    targets = []
    if data.get("dm"):
        targets.append("личные чаты")
    if data.get("groups"):
        targets.append("группы")
    target_str = " + ".join(targets)

    await message.reply(
        f"📢 <b>Превью рассылки</b>\n\n"
        f"📬 Куда: <b>{target_str}</b>\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{escape(text)}\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"Отправить?",
        reply_markup=_confirm_kb(),
        parse_mode="HTML",
    )


@router.callback_query(BroadcastStates.waiting_for_confirm, F.data == "bcast_send")
async def cb_broadcast_send(
    callback: CallbackQuery, state: FSMContext, session: AsyncSession, bot: Bot
) -> None:
    await callback.answer()
    data = await state.get_data()
    dm = data.get("dm", False)
    groups = data.get("groups", False)
    text = data.get("text", "")
    entities_data = data.get("entities", [])

    # Rebuild entities
    entities = []
    for e in entities_data:
        kwargs: dict = {
            "type": e["type"],
            "offset": e["offset"],
            "length": e["length"],
        }
        if e.get("url"):
            kwargs["url"] = e["url"]
        if e.get("language"):
            kwargs["language"] = e["language"]
        if e.get("custom_emoji_id"):
            kwargs["custom_emoji_id"] = e["custom_emoji_id"]
        entities.append(MessageEntity(**kwargs))

    # Query target chats
    types_to_include = []
    if dm:
        types_to_include.append("private")
    if groups:
        types_to_include.extend(["group", "supergroup"])

    result = await session.execute(
        select(KnownChat.chat_id)
        .where(KnownChat.chat_type.in_(types_to_include))
        .where(KnownChat.is_active == True)  # noqa: E712
    )
    chat_ids = [row[0] for row in result.all()]
    total = len(chat_ids)

    await callback.message.edit_text(
        f"📢 Рассылка начата: 0/{total}",
    )

    sent = 0
    failed = 0
    for i, chat_id in enumerate(chat_ids):
        try:
            await bot.send_message(chat_id, text, entities=entities or None)
            sent += 1
        except Exception as exc:
            failed += 1
            logger.debug(f"Broadcast failed for chat {chat_id}: {exc}")
            # Mark chat inactive on hard errors (blocked, kicked)
            err_str = str(exc).lower()
            if any(k in err_str for k in ["blocked", "forbidden", "kicked", "not found", "deactivated"]):
                try:
                    chat = await session.get(KnownChat, chat_id)
                    if chat is not None:
                        chat.is_active = False
                except Exception:
                    pass
        # Progress update every 10 sends
        if (i + 1) % 10 == 0 or (i + 1) == total:
            try:
                await callback.message.edit_text(
                    f"📢 Рассылка: {i + 1}/{total} (✅ {sent}, ❌ {failed})"
                )
            except Exception:
                pass
        # Rate limit compliance: ~30 msg/s max
        await asyncio.sleep(0.04)

    await state.clear()
    await callback.message.edit_text(
        f"✅ <b>Рассылка завершена</b>\n\n"
        f"📬 Всего: {total}\n"
        f"✅ Отправлено: {sent}\n"
        f"❌ Ошибок: {failed}",
        parse_mode="HTML",
    )


@router.callback_query(F.data == "bcast_cancel")
async def cb_broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer("Отменено.")
    await state.clear()
    await callback.message.edit_text("❌ Рассылка отменена.")
