"""Middleware that records every chat the bot sees into known_chats."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.known_chat import KnownChat

logger = logging.getLogger(__name__)


class ChatTrackerMiddleware(BaseMiddleware):
    """Records chat info on every incoming update (lazy upsert)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        chat = None
        if isinstance(event, Message):
            chat = event.chat
        elif isinstance(event, CallbackQuery) and event.message:
            chat = event.message.chat

        if chat is not None:
            session: AsyncSession = data.get("session")
            if session is not None:
                try:
                    existing = await session.get(KnownChat, chat.id)
                    now = datetime.utcnow()
                    if existing is None:
                        known = KnownChat(
                            chat_id=chat.id,
                            chat_type=chat.type,
                            title=chat.title or chat.full_name or "",
                            last_seen=now,
                        )
                        session.add(known)
                    else:
                        existing.last_seen = now
                        existing.chat_type = chat.type
                        if chat.title or (hasattr(chat, 'full_name') and chat.full_name):
                            existing.title = chat.title or chat.full_name
                        existing.is_active = True
                except Exception as exc:
                    logger.warning(f"ChatTracker failed: {exc}")

        return await handler(event, data)
