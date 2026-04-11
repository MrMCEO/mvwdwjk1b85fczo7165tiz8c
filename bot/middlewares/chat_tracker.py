"""Middleware that records every chat the bot sees into known_chats."""
from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.known_chat import KnownChat

logger = logging.getLogger(__name__)

# In-process TTL cache: chat_id -> monotonic timestamp of last DB write.
# Chats seen within TTL_SECONDS are skipped for DB reads/writes entirely.
_seen_recently: dict[int, float] = {}
TTL_SECONDS = 60.0
_CLEANUP_THRESHOLD = 500  # trigger cleanup when dict exceeds this size


class ChatTrackerMiddleware(BaseMiddleware):
    """Records chat info on every incoming update (lazy upsert).

    Uses a module-level TTL cache so that repeated updates from the same chat
    within TTL_SECONDS do not hit the database at all.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        global _seen_recently

        chat = None
        if isinstance(event, Message):
            chat = event.chat
        elif isinstance(event, CallbackQuery) and event.message:
            chat = event.message.chat

        if chat is not None:
            now_ts = time.monotonic()
            last_seen = _seen_recently.get(chat.id)

            if last_seen is not None and (now_ts - last_seen) < TTL_SECONDS:
                # Seen recently — skip DB entirely
                return await handler(event, data)

            # Update cache before DB work so concurrent coroutines don't
            # all rush the DB simultaneously for the same chat.
            _seen_recently[chat.id] = now_ts

            # Periodic cleanup: evict expired entries to keep memory bounded.
            if len(_seen_recently) > _CLEANUP_THRESHOLD:
                cutoff = now_ts - TTL_SECONDS
                _seen_recently = {k: v for k, v in _seen_recently.items() if v > cutoff}

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
                        if chat.title or (hasattr(chat, "full_name") and chat.full_name):
                            existing.title = chat.title or chat.full_name
                        existing.is_active = True
                except Exception as exc:
                    logger.warning(f"ChatTracker failed: {exc}")

        return await handler(event, data)
