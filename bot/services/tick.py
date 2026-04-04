"""
Tick service — periodic processing of active infections.

Every tick (default: 60 minutes):
  - Each active Infection drains bio_coins from the victim.
  - 70% of the drained amount goes to the attacker.
  - Both transfers are recorded as ResourceTransaction rows.
  - There is a per-infection auto-cure roll: 5% base + victim's recovery_speed.
  - Cured infections are deactivated and a notification is generated.

start_scheduler() sets up an APScheduler AsyncIOScheduler to call
process_infection_tick() at the configured interval and sends Telegram
notifications via the Bot instance.
"""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models.base import AsyncSessionFactory
from bot.models.infection import Infection
from bot.models.resource import Currency as CurrencyType
from bot.models.resource import ResourceTransaction, TransactionReason
from bot.models.user import User

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TICK_INTERVAL_MINUTES: int = 60

# Attacker receives this fraction of stolen bio_coins
ATTACKER_SHARE: float = 0.70

# Base auto-cure chance per tick (5%)
BASE_CURE_CHANCE: float = 0.05

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Core tick logic
# ---------------------------------------------------------------------------


async def process_infection_tick(session: AsyncSession) -> list[dict]:
    """
    Process all active infections for one tick.

    Returns a list of notification dicts:
        {"user_id": int, "message": str}

    Caller is responsible for committing the session after this returns.
    """
    notifications: list[dict] = []

    # Load all active infections (with attacker/victim users and victim immunity eager-loaded)
    result = await session.execute(
        select(Infection)
        .where(Infection.is_active == True)  # noqa: E712
        .options(
            selectinload(Infection.attacker),
            selectinload(Infection.victim).selectinload(User.immunity),
        )
    )
    infections: list[Infection] = list(result.scalars().all())

    if not infections:
        logger.debug("Tick: no active infections to process.")
        return notifications

    logger.info("Tick: processing %d active infection(s).", len(infections))

    for inf in infections:
        victim: User = inf.victim
        attacker: User = inf.attacker

        # --- Drain bio_coins from victim ---
        # Use round() to avoid permanently discarding fractional damage each tick.
        drain = min(round(inf.damage_per_tick), victim.bio_coins)  # cannot go below 0
        if drain < 0:
            drain = 0

        if drain > 0:
            victim.bio_coins -= drain

            # Record loss for victim
            loss_tx = ResourceTransaction(
                user_id=victim.tg_id,
                amount=-drain,
                currency=CurrencyType.BIO_COINS,
                reason=TransactionReason.INFECTION_LOSS,
            )
            session.add(loss_tx)

            # Attacker receives 70%
            attacker_gain = int(drain * ATTACKER_SHARE)
            if attacker_gain > 0:
                attacker.bio_coins += attacker_gain

                income_tx = ResourceTransaction(
                    user_id=attacker.tg_id,
                    amount=attacker_gain,
                    currency=CurrencyType.BIO_COINS,
                    reason=TransactionReason.INFECTION_INCOME,
                )
                session.add(income_tx)

                notifications.append({
                    "user_id": attacker.tg_id,
                    "message": (
                        f"Пассивный доход: +{attacker_gain} bio_coins "
                        f"от заражения игрока {victim.username or str(victim.tg_id)}."
                    ),
                })

            notifications.append({
                "user_id": victim.tg_id,
                "message": (
                    f"Вирус продолжает наносить урон: -{drain} bio_coins. "
                    f"Баланс: {victim.bio_coins} bio_coins."
                ),
            })

        # --- Auto-cure roll --- use eagerly-loaded immunity (avoids N+1 query)
        recovery_speed = victim.immunity.recovery_speed if victim.immunity else 0.0
        cure_chance = BASE_CURE_CHANCE + recovery_speed
        cure_chance = max(0.0, min(1.0, cure_chance))

        if random.random() < cure_chance:
            inf.is_active = False
            logger.info(
                "Tick: infection #%d cured (auto). victim=%d",
                inf.id, victim.tg_id,
            )
            notifications.append({
                "user_id": victim.tg_id,
                "message": (
                    f"Твой иммунитет победил! "
                    f"Заражение #{inf.id} вылечено автоматически."
                ),
            })
            notifications.append({
                "user_id": attacker.tg_id,
                "message": (
                    f"Игрок {victim.username or str(victim.tg_id)} "
                    f"вылечился от твоего вируса (заражение #{inf.id})."
                ),
            })

    await session.flush()
    return notifications


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


async def start_scheduler(bot) -> None:  # bot: aiogram.Bot
    """
    Start the APScheduler AsyncIOScheduler that triggers infection ticks.

    Creates a fresh DB session for every tick execution so that the scheduler
    is decoupled from request lifecycle sessions.
    """
    scheduler = AsyncIOScheduler(timezone="UTC")

    async def _tick_job() -> None:
        logger.info("Scheduler: starting infection tick...")
        async with AsyncSessionFactory() as session:
            try:
                notifications = await process_infection_tick(session)
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("Scheduler: tick failed, transaction rolled back.")
                return

        # Send notifications outside the DB session
        for note in notifications:
            try:
                await bot.send_message(
                    chat_id=note["user_id"],
                    text=note["message"],
                )
            except Exception as exc:
                # User may have blocked the bot — log and continue
                logger.warning(
                    "Scheduler: could not send notification to %s: %s",
                    note["user_id"], exc,
                )

        logger.info(
            "Scheduler: tick complete, %d notification(s) sent.", len(notifications)
        )

    scheduler.add_job(
        _tick_job,
        trigger="interval",
        minutes=TICK_INTERVAL_MINUTES,
        id="infection_tick",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler: infection tick started (interval=%d min).",
        TICK_INTERVAL_MINUTES,
    )
