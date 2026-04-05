"""
Unit tests for bot/services/transfer.py
"""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.resource import Currency, ResourceTransaction, TransactionReason
from bot.models.user import User
from bot.services.player import create_player
from bot.services.transfer import (
    DEFAULT_DAILY_LIMIT,
    TRANSFER_COMMISSION,
    transfer_coins,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _naive_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _set_bio_coins(session: AsyncSession, tg_id: int, amount: int) -> None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = result.scalar_one()
    user.bio_coins = amount
    await session.flush()


async def _exhaust_daily_limit(
    session: AsyncSession, sender_id: int, recipient_id: int
) -> None:
    """Insert TRANSFER_OUT transactions to fill the sender's daily limit."""
    tx = ResourceTransaction(
        user_id=sender_id,
        amount=-DEFAULT_DAILY_LIMIT,
        currency=Currency.BIO_COINS,
        reason=TransactionReason.TRANSFER_OUT,
    )
    session.add(tx)
    await session.flush()


# ---------------------------------------------------------------------------
# test_transfer_success
# ---------------------------------------------------------------------------


async def test_transfer_success(session: AsyncSession):
    """A valid transfer deducts from the sender and credits the recipient."""
    await create_player(session, tg_id=8001, username="sender1")
    await create_player(session, tg_id=8002, username="recipient1")
    await _set_bio_coins(session, 8001, 200)

    success, msg = await transfer_coins(
        session, sender_id=8001, recipient_username="recipient1", amount=100
    )

    assert success is True
    assert "выполнен" in msg.lower() or "✅" in msg

    sender_result = await session.execute(select(User).where(User.tg_id == 8001))
    sender = sender_result.scalar_one()
    assert sender.bio_coins == 100  # 200 - 100 sent

    recipient_result = await session.execute(select(User).where(User.tg_id == 8002))
    recipient = recipient_result.scalar_one()
    commission = max(1, int(100 * TRANSFER_COMMISSION))
    assert recipient.bio_coins == 500 + 100 - commission  # 500 starting + received amount


# ---------------------------------------------------------------------------
# test_transfer_self
# ---------------------------------------------------------------------------


async def test_transfer_self(session: AsyncSession):
    """Transferring to oneself returns a failure."""
    await create_player(session, tg_id=8010, username="selfuser")
    await _set_bio_coins(session, 8010, 500)

    success, msg = await transfer_coins(
        session, sender_id=8010, recipient_username="selfuser", amount=50
    )

    assert success is False
    assert "самому себе" in msg or "нельзя" in msg.lower()


# ---------------------------------------------------------------------------
# test_transfer_not_enough
# ---------------------------------------------------------------------------


async def test_transfer_not_enough(session: AsyncSession):
    """Transfer fails when sender doesn't have enough bio_coins."""
    await create_player(session, tg_id=8020, username="poor_sender")
    await create_player(session, tg_id=8021, username="rich_recipient")
    await _set_bio_coins(session, 8020, 10)

    success, msg = await transfer_coins(
        session, sender_id=8020, recipient_username="rich_recipient", amount=100
    )

    assert success is False
    assert "Недостаточно" in msg or "недостаточно" in msg.lower()


# ---------------------------------------------------------------------------
# test_transfer_daily_limit
# ---------------------------------------------------------------------------


async def test_transfer_daily_limit(session: AsyncSession):
    """Transfer fails when the daily limit has been reached."""
    await create_player(session, tg_id=8030, username="limited_sender")
    await create_player(session, tg_id=8031, username="limited_recipient")
    await _set_bio_coins(session, 8030, DEFAULT_DAILY_LIMIT * 2)

    # Exhaust the daily limit via a raw transaction record
    await _exhaust_daily_limit(session, sender_id=8030, recipient_id=8031)

    success, msg = await transfer_coins(
        session, sender_id=8030, recipient_username="limited_recipient", amount=1
    )

    assert success is False
    assert "лимит" in msg.lower() or "Превышен" in msg


# ---------------------------------------------------------------------------
# test_transfer_commission
# ---------------------------------------------------------------------------


async def test_transfer_commission(session: AsyncSession):
    """Recipient receives amount minus the 10% commission."""
    await create_player(session, tg_id=8040, username="comm_sender")
    await create_player(session, tg_id=8041, username="comm_recipient")
    await _set_bio_coins(session, 8040, 500)

    amount = 200
    success, msg = await transfer_coins(
        session, sender_id=8040, recipient_username="comm_recipient", amount=amount
    )

    assert success is True

    expected_commission = max(1, int(amount * TRANSFER_COMMISSION))
    expected_received = amount - expected_commission

    result = await session.execute(select(User).where(User.tg_id == 8041))
    recipient = result.scalar_one()
    assert recipient.bio_coins == 500 + expected_received  # 500 starting + received amount

    # Check that the message mentions the commission amount
    assert str(expected_commission) in msg
