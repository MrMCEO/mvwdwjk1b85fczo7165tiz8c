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
import math
import random
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from html import escape

from bot.models.base import AsyncSessionFactory
from bot.models.immunity import Immunity, ImmunityBranch, ImmunityUpgrade
from bot.models.infection import Infection
from bot.models.resource import Currency as CurrencyType
from bot.models.resource import ResourceTransaction, TransactionReason
from bot.models.user import User
from bot.models.virus import Virus, VirusUpgrade
from bot.services.alliance import get_alliance_regen_bonus
from bot.services.event import expire_events
from bot.services.notifications import should_notify
from bot.services.player import DEFAULT_VIRUS_NAME
from bot.services.premium import format_username
from bot.services.referral import deactivate_stale_referrals

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TICK_INTERVAL_MINUTES: int = 60

# Virus names that are considered "not custom" — mirrors the same set in combat.py.
_NON_CUSTOM: frozenset[str] = frozenset({"", "—", DEFAULT_VIRUS_NAME})

# Attacker receives this fraction of stolen bio_coins.
# Lowered from 70% to 50%: attacking is still profitable but not a
# gold mine. Victim loses 5/tick, attacker gains 2.5/tick at base.
ATTACKER_SHARE: float = 0.50

# Base auto-cure chance per tick (5%). With default recovery_speed=0.03
# total newbie chance = 8% per tick. Expected infection: ~12 ticks (12hrs).
# Total expected loss: 5 * 12 = 60 bio_coins. Cure cost: 5 * 8 = 40.
# So manual cure IS worth it — good decision point for the player.
BASE_CURE_CHANCE: float = 0.05

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _fmt_user(user: User) -> str:
    """Return a display name for a User, using display_name and premium prefix if active."""
    now = _now_utc()
    is_active = user.premium_until is not None and user.premium_until > now
    base = f"@{user.username}" if user.username else str(user.tg_id)
    return format_username(base, user.premium_prefix, is_active, display_name=user.display_name)


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

    # Load all active infections (with attacker/victim users, victim immunity + upgrades,
    # victim virus + upgrades for total_level, and attacker's virus for name display)
    result = await session.execute(
        select(Infection)
        .where(Infection.is_active == True)  # noqa: E712
        .options(
            selectinload(Infection.attacker).selectinload(User.virus),
            selectinload(Infection.victim)
            .selectinload(User.immunity)
            .selectinload(Immunity.upgrades),  # needed for REGENERATION effect
            selectinload(Infection.victim)
            .selectinload(User.virus)
            .selectinload(Virus.upgrades),  # needed for drain total_level calculation
        )
    )
    infections: list[Infection] = list(result.scalars().all())

    if not infections:
        logger.debug("Tick: no active infections to process.")
        return notifications

    logger.info("Tick: processing %d active infection(s).", len(infections))

    cured_count = 0

    for inf in infections:
        victim: User = inf.victim
        attacker: User = inf.attacker

        # --- Compute scalable drain ---
        # victim_total_level = sum of all virus branch levels + all immunity branch levels
        victim_virus = getattr(victim, "virus", None)
        victim_virus_level = (
            sum(u.level for u in victim_virus.upgrades)
            if victim_virus is not None and victim_virus.upgrades
            else 0
        )
        victim_immunity = victim.immunity
        victim_immunity_level = (
            sum(u.level for u in victim_immunity.upgrades)
            if victim_immunity is not None and victim_immunity.upgrades
            else 0
        )
        victim_total_level = victim_virus_level + victim_immunity_level

        # Use actual damage_per_tick from the infection (set by attacker's LETHALITY)
        base_drain = inf.damage_per_tick  # already stored on infection creation

        # BARRIER reduces drain (soft scaling, 70% cap)
        barrier_effect = 0.0
        if victim_immunity is not None and victim_immunity.upgrades:
            for u in victim_immunity.upgrades:
                if u.branch == ImmunityBranch.BARRIER:
                    barrier_level = u.level
                    barrier_effect = barrier_level * 1.5 * (1 - barrier_level / 120)
                    break

        # Minimum 30% of base damage always gets through (70% reduction cap)
        actual_drain = max(math.floor(base_drain * 0.30), base_drain - barrier_effect)
        actual_drain = max(1, int(actual_drain))  # minimum 1 coin drain

        # Minimum balance the victim can reach: -(total_level * 200)
        victim_min_balance = -(victim_total_level * 200)

        # Drain stops at debt cap
        if victim.bio_coins <= victim_min_balance:
            actual_drain = 0

        if actual_drain > 0:
            victim.bio_coins = victim.bio_coins - actual_drain

            # Record loss for victim
            loss_tx = ResourceTransaction(
                user_id=victim.tg_id,
                amount=-actual_drain,
                currency=CurrencyType.BIO_COINS,
                reason=TransactionReason.INFECTION_LOSS,
            )
            session.add(loss_tx)

            # Attacker receives ATTACKER_SHARE of actual drained amount
            attacker_gain = int(actual_drain * ATTACKER_SHARE)
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
                    "notify_type": "infections",
                    "message": (
                        f"Пассивный доход: +{attacker_gain} 🧫 BioCoins "
                        f"от заражения игрока {_fmt_user(victim)}."
                    ),
                })

            # Build victim drain notification with optional custom virus name
            attacker_virus = getattr(attacker, "virus", None)
            if attacker_virus is not None and attacker_virus.name not in _NON_CUSTOM:
                drain_msg = (
                    f"🦠 Вирус «{escape(attacker_virus.name)}» "
                    f"забрал у вас {actual_drain} 🧫 BioCoins"
                )
            else:
                drain_msg = f"🦠 Заражение забрало у вас {actual_drain} 🧫 BioCoins"

            notifications.append({
                "user_id": victim.tg_id,
                "notify_type": "infections",
                "message": drain_msg,
            })

        # --- Duration expiry check (CONTAGION determines duration_ticks) ---
        if inf.duration_ticks is not None:
            if inf.started_at:
                hours_elapsed = (_now_utc() - inf.started_at).total_seconds() / 3600
                ticks_elapsed = int(hours_elapsed)  # 1 tick = 1 hour
                if ticks_elapsed >= inf.duration_ticks:
                    inf.is_active = False
                    cured_count += 1
                    logger.info(
                        "Tick: infection #%d expired by duration (%d ticks). victim=%d",
                        inf.id, inf.duration_ticks, victim.tg_id,
                    )
                    notifications.append({
                        "user_id": victim.tg_id,
                        "notify_type": "infections",
                        "message": (
                            f"Твой иммунитет победил! "
                            f"Заражение #{inf.id} вылечено автоматически."
                        ),
                    })
                    notifications.append({
                        "user_id": attacker.tg_id,
                        "notify_type": "infections",
                        "message": (
                            f"Игрок {_fmt_user(victim)} "
                            f"вылечился от твоего вируса (заражение #{inf.id})."
                        ),
                    })
                    continue

        # --- Auto-cure roll ---
        # Base: 5% + recovery_speed (0.03 default) = 8% for newbie.
        # REGENERATION upgrade adds +0.02/level to cure chance.
        # Lvl10 regen: 5% + 3% + 20% = 28% per tick (~3.6 tick avg duration).
        recovery_speed = victim.immunity.recovery_speed if victim.immunity else 0.0
        regen_bonus = 0.0
        if victim.immunity and victim.immunity.upgrades:
            for u in victim.immunity.upgrades:
                if u.branch == ImmunityBranch.REGENERATION and u.level > 0:
                    regen_bonus = u.effect_value
                    break
        alliance_regen = await get_alliance_regen_bonus(session, victim.tg_id)
        cure_chance = BASE_CURE_CHANCE + recovery_speed + regen_bonus + alliance_regen
        cure_chance = max(0.0, min(0.60, cure_chance))  # cap at 60% — infection should always have some duration

        if random.random() < cure_chance:
            inf.is_active = False
            cured_count += 1
            logger.info(
                "Tick: infection #%d cured (auto). victim=%d",
                inf.id, victim.tg_id,
            )
            notifications.append({
                "user_id": victim.tg_id,
                "notify_type": "infections",
                "message": (
                    f"Твой иммунитет победил! "
                    f"Заражение #{inf.id} вылечено автоматически."
                ),
            })
            notifications.append({
                "user_id": attacker.tg_id,
                "notify_type": "infections",
                "message": (
                    f"Игрок {_fmt_user(victim)} "
                    f"вылечился от твоего вируса (заражение #{inf.id})."
                ),
            })

    logger.info(f"Tick processed: {len(infections)} infections, {cured_count} cured")
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
                stale_count = await deactivate_stale_referrals(session)
                if stale_count:
                    logger.info(
                        "Scheduler: deactivated %d stale referral(s).", stale_count
                    )
                expired_count, event_notifications = await expire_events(session)
                if expired_count:
                    logger.info(
                        "Scheduler: expired %d event(s), %d prize notification(s).",
                        expired_count, len(event_notifications),
                    )
                    notifications.extend(event_notifications)
                await session.commit()
            except Exception:
                await session.rollback()
                logger.exception("Scheduler: tick failed, transaction rolled back.")
                return

        # Send notifications outside the DB session (check user prefs first)
        sent_count = 0
        async with AsyncSessionFactory() as notify_session:
            for note in notifications:
                notify_type = note.get("notify_type")
                if notify_type:
                    allowed = await should_notify(notify_session, note["user_id"], notify_type)
                    if not allowed:
                        continue
                try:
                    await bot.send_message(
                        chat_id=note["user_id"],
                        text=note["message"],
                        parse_mode="HTML",
                    )
                    sent_count += 1
                except Exception as exc:
                    # User may have blocked the bot — log and continue
                    logger.warning(
                        "Scheduler: could not send notification to %s: %s",
                        note["user_id"], exc,
                    )

        logger.info(
            "Scheduler: tick complete, %d/%d notification(s) sent.",
            sent_count, len(notifications),
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
