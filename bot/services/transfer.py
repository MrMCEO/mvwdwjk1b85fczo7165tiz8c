"""
Transfer service — peer-to-peer bio_coin transfers between players.

Commission: 5% (recipient receives amount * 0.95).
Daily limit: varies by premium status (see premium.get_transfer_limit()).
             FREE: 1500 🧫 / day. Higher status tiers increase the limit.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.resource import Currency, ResourceTransaction, TransactionReason
from bot.models.user import User
from bot.services import premium as _premium

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRANSFER_COMMISSION = 0.05   # 5% комиссия
DEFAULT_DAILY_LIMIT = 1500   # 🧫 BioCoins в день (базовый лимит для FREE)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_transfer_limit(session: AsyncSession, user_id: int) -> int:
    """
    Вернуть дневной лимит переводов для игрока по его статусу.

    Делегирует в premium.get_transfer_limit() — учитывает статус (FREE/BIO_PLUS/…).
    """
    return await _premium.get_transfer_limit(session, user_id)


async def get_daily_transferred(session: AsyncSession, user_id: int) -> int:
    """Сколько 🧫 уже было переведено за последние 24 часа."""
    since = _now_utc() - timedelta(hours=24)
    result = await session.execute(
        select(func.coalesce(func.sum(ResourceTransaction.amount), 0))
        .where(
            ResourceTransaction.user_id == user_id,
            ResourceTransaction.reason == TransactionReason.TRANSFER_OUT,
            ResourceTransaction.created_at >= since,
        )
    )
    # amount is stored as negative for outgoing, so abs it
    raw: int = result.scalar_one()
    return abs(raw)


async def transfer_coins(
    session: AsyncSession,
    sender_id: int,
    recipient_username: str,
    amount: int,
) -> tuple[bool, str]:
    """
    Перевести 🧫 BioCoins другому игроку.

    Правила:
    - Нельзя переводить самому себе.
    - Минимальная сумма: 1.
    - Комиссия 10%: получатель получает amount * 0.9 (floor).
    - Проверка дневного лимита (сумма исходящих переводов за 24ч).
    - Создаёт ResourceTransaction для отправителя (TRANSFER_OUT) и получателя (TRANSFER_IN).

    Возвращает (True, success_msg) или (False, error_msg).
    """
    if amount <= 0:
        return False, "❌ Сумма перевода должна быть больше нуля."

    # Find recipient
    raw_username = recipient_username.strip().lstrip("@")
    if not raw_username:
        return False, "❌ Укажи @username получателя."

    recipient_result = await session.execute(
        select(User).where(func.lower(User.username) == raw_username.lower())
    )
    recipient = recipient_result.scalar_one_or_none()
    if recipient is None:
        return False, f"❌ Игрок <b>@{raw_username}</b> не найден в игре."

    if recipient.tg_id == sender_id:
        return False, "❌ Нельзя переводить монеты самому себе."

    # Check daily limit
    daily_limit = await get_transfer_limit(session, sender_id)
    already_sent = await get_daily_transferred(session, sender_id)
    if already_sent + amount > daily_limit:
        remaining = max(0, daily_limit - already_sent)
        return False, (
            f"❌ Превышен дневной лимит переводов.\n"
            f"Использовано: <b>{already_sent}/{daily_limit} 🧫</b>\n"
            f"Доступно: <b>{remaining} 🧫</b>"
        )

    # Lock sender
    sender_result = await session.execute(
        select(User).where(User.tg_id == sender_id).with_for_update()
    )
    sender = sender_result.scalar_one_or_none()
    if sender is None:
        return False, "❌ Пользователь не найден."

    if sender.bio_coins < amount:
        return False, (
            f"❌ Недостаточно 🧫 BioCoins.\n"
            f"Нужно: {amount} 🧫, у тебя: {sender.bio_coins} 🧫"
        )

    # Lock recipient
    recipient_locked_result = await session.execute(
        select(User).where(User.tg_id == recipient.tg_id).with_for_update()
    )
    recipient = recipient_locked_result.scalar_one_or_none()

    # Calculate commission
    commission = max(1, int(amount * TRANSFER_COMMISSION))  # at least 1 if amount > 0
    received = amount - commission

    # Apply
    sender.bio_coins -= amount
    recipient.bio_coins += received

    # Audit trail
    tx_out = ResourceTransaction(
        user_id=sender_id,
        amount=-amount,
        currency=Currency.BIO_COINS,
        reason=TransactionReason.TRANSFER_OUT,
    )
    tx_in = ResourceTransaction(
        user_id=recipient.tg_id,
        amount=received,
        currency=Currency.BIO_COINS,
        reason=TransactionReason.TRANSFER_IN,
    )
    session.add(tx_out)
    session.add(tx_in)
    await session.flush()

    recipient_display = (
        f"@{recipient.username}" if recipient.username else f"id{recipient.tg_id}"
    )
    return True, (
        f"✅ Перевод выполнен!\n\n"
        f"Отправлено: <b>{amount} 🧫</b>\n"
        f"Комиссия (5%): <b>{commission} 🧫</b>\n"
        f"Получено игроком <b>{recipient_display}</b>: <b>{received} 🧫</b>\n\n"
        f"Твой баланс: <b>{sender.bio_coins} 🧫</b>"
    )
