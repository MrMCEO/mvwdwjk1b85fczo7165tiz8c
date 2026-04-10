"""Database logging helper — writes structured events to bot_logs table."""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.bot_log import BotLog

_logger = logging.getLogger(__name__)


async def log_event(
    session: AsyncSession,
    event_type: str,
    user_id: int | None = None,
    message: str = "",
    level: str = "INFO",
    extra: dict[str, Any] | None = None,
) -> None:
    """
    Log a structured event to the bot_logs table.

    Args:
        session: Active DB session (will be flushed, not committed).
        event_type: Short identifier (e.g. "attack", "upgrade", "registration").
        user_id: Telegram user ID associated with the event (optional).
        message: Human-readable description.
        level: INFO / WARN / ERROR. Defaults to INFO.
        extra: Optional structured data (JSON-serializable).

    The DB write is swallowed on error — logging must never break the main flow.
    """
    try:
        log = BotLog(
            event_type=event_type,
            user_id=user_id,
            message=message,
            level=level,
            extra=extra,
        )
        session.add(log)
        # Don't commit — let the outer transaction handle it
    except Exception as exc:
        _logger.warning(f"Failed to write bot_log: {exc}")
