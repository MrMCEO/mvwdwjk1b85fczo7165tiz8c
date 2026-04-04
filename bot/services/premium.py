"""
Premium subscription service.

A premium subscription costs PREMIUM_COST 💎 PremiumCoins per month and grants
various gameplay perks. The subscription is stored as ``User.premium_until``
(naive UTC datetime). None means no active subscription.

All perk values are defined here — never hardcode them in other services.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from html import escape as _html_escape

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.user import User

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

PREMIUM_COST = 200           # 💎 PremiumCoins per month
PREMIUM_DURATION_DAYS = 30

PREMIUM_PERKS: dict[str, float | int] = {
    "mining_bonus": 0.25,              # +25% to mining yield
    "daily_bonus": 0.50,               # +50% to daily bonus
    "mining_cooldown_minutes": 45,     # vs. 60 for regular
    "attack_cooldown_minutes": 25,     # vs. 30 for regular
    "max_attempts_per_target": 4,      # vs. 3 for regular
    "max_infections_per_hour": 6,      # vs. 5 for regular
    "virus_name_length": 30,           # vs. 20 for regular
}

# Defaults for non-premium users (mirrors hardcoded values elsewhere)
_DEFAULT_MINING_COOLDOWN_MINUTES = 60
_DEFAULT_ATTACK_COOLDOWN_MINUTES = 30
_DEFAULT_MAX_ATTEMPTS_PER_TARGET = 3
_DEFAULT_MAX_INFECTIONS_PER_HOUR = 5
_DEFAULT_VIRUS_NAME_LENGTH = 20


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    """Return current naive UTC datetime (stored without tzinfo in DB)."""
    return datetime.now(UTC).replace(tzinfo=None)


async def _get_user(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_id == user_id))
    return result.scalar_one_or_none()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def is_premium(session: AsyncSession, user_id: int) -> bool:
    """Return True if the user has an active premium subscription right now."""
    user = await _get_user(session, user_id)
    if user is None or user.premium_until is None:
        return False
    return user.premium_until > _now_utc()


async def buy_premium(session: AsyncSession, user_id: int) -> tuple[bool, str]:
    """
    Purchase or extend a premium subscription for *user_id*.

    Costs PREMIUM_COST 💎 PremiumCoins.
    - If the subscription is already active: extends from the current expiry date.
    - If expired / not present: starts from now.

    Returns (success, message).
    """
    result = await session.execute(
        select(User).where(User.tg_id == user_id).with_for_update()
    )
    user = result.scalar_one_or_none()
    if user is None:
        return False, "Пользователь не найден."

    if user.premium_coins < PREMIUM_COST:
        return False, (
            f"Недостаточно 💎 PremiumCoins. Нужно {PREMIUM_COST}, "
            f"у тебя {user.premium_coins}."
        )

    now = _now_utc()
    duration = timedelta(days=PREMIUM_DURATION_DAYS)

    # Extend from current expiry if still active, otherwise from now
    if user.premium_until is not None and user.premium_until > now:
        new_until = user.premium_until + duration
        action = "продлена"
    else:
        new_until = now + duration
        action = "активирована"

    user.premium_coins -= PREMIUM_COST
    user.premium_until = new_until
    await session.flush()

    until_str = new_until.strftime("%d.%m.%Y")
    return True, (
        f"⭐ Подписка {action}! Действует до {until_str}.\n"
        f"Потрачено {PREMIUM_COST} 💎 PremiumCoins."
    )


async def get_premium_info(session: AsyncSession, user_id: int) -> dict:
    """
    Return a dict with premium status info for *user_id*.

    Keys:
      is_active : bool
      until     : datetime | None   — expiry datetime (naive UTC) or None
      days_left : int               — full days remaining (0 if not active)
    """
    user = await _get_user(session, user_id)
    if user is None or user.premium_until is None:
        return {"is_active": False, "until": None, "days_left": 0}

    now = _now_utc()
    if user.premium_until <= now:
        return {"is_active": False, "until": user.premium_until, "days_left": 0}

    days_left = (user.premium_until - now).days
    return {
        "is_active": True,
        "until": user.premium_until,
        "days_left": days_left,
    }


# ---------------------------------------------------------------------------
# Perk getters — always use these in other services, never hardcode numbers
# ---------------------------------------------------------------------------


async def get_mining_cooldown(session: AsyncSession, user_id: int) -> timedelta:
    """Return mining cooldown: 45 min for premium, 60 min for regular users."""
    if await is_premium(session, user_id):
        return timedelta(minutes=int(PREMIUM_PERKS["mining_cooldown_minutes"]))
    return timedelta(minutes=_DEFAULT_MINING_COOLDOWN_MINUTES)


async def get_attack_cooldown(session: AsyncSession, user_id: int) -> timedelta:
    """Return attack cooldown: 25 min for premium, 30 min for regular users."""
    if await is_premium(session, user_id):
        return timedelta(minutes=int(PREMIUM_PERKS["attack_cooldown_minutes"]))
    return timedelta(minutes=_DEFAULT_ATTACK_COOLDOWN_MINUTES)


async def get_attack_limits(session: AsyncSession, user_id: int) -> tuple[int, int]:
    """
    Return (max_attempts_per_target, max_infections_per_hour).
    Premium: (4, 6). Regular: (3, 5).
    """
    if await is_premium(session, user_id):
        return (
            int(PREMIUM_PERKS["max_attempts_per_target"]),
            int(PREMIUM_PERKS["max_infections_per_hour"]),
        )
    return _DEFAULT_MAX_ATTEMPTS_PER_TARGET, _DEFAULT_MAX_INFECTIONS_PER_HOUR


async def get_virus_name_limit(session: AsyncSession, user_id: int) -> int:
    """Return max virus name length: 30 for premium, 20 for regular users."""
    if await is_premium(session, user_id):
        return int(PREMIUM_PERKS["virus_name_length"])
    return _DEFAULT_VIRUS_NAME_LENGTH


async def get_mining_multiplier(session: AsyncSession, user_id: int) -> float:
    """Return mining yield multiplier: 1.25 for premium, 1.0 for regular users."""
    if await is_premium(session, user_id):
        return 1.0 + float(PREMIUM_PERKS["mining_bonus"])
    return 1.0


async def get_daily_multiplier(session: AsyncSession, user_id: int) -> float:
    """Return daily bonus multiplier: 1.5 for premium, 1.0 for regular users."""
    if await is_premium(session, user_id):
        return 1.0 + float(PREMIUM_PERKS["daily_bonus"])
    return 1.0


# ---------------------------------------------------------------------------
# Premium prefix
# ---------------------------------------------------------------------------

PREFIX_MAX_CHARS = 5


async def set_prefix(session: AsyncSession, user_id: int, prefix: str) -> tuple[bool, str]:
    """
    Установить кастомный префикс для премиум-пользователя.

    Правила:
      - Только для активных премиум-подписчиков.
      - Длина: не более PREFIX_MAX_CHARS видимых символов.
      - Применяется html.escape() для безопасности.

    Возвращает (success, message).
    """
    result = await session.execute(
        select(User).where(User.tg_id == user_id).with_for_update()
    )
    user = result.scalar_one_or_none()
    if user is None:
        return False, "Пользователь не найден."

    now = _now_utc()
    if user.premium_until is None or user.premium_until <= now:
        return False, "❌ Кастомный префикс доступен только для премиум-подписчиков."

    stripped = prefix.strip()
    if len(stripped) > PREFIX_MAX_CHARS:
        return False, (
            f"❌ Префикс слишком длинный. Максимум {PREFIX_MAX_CHARS} символов, "
            f"у тебя {len(stripped)}."
        )
    if not stripped:
        return False, "❌ Префикс не может быть пустым."

    safe = _html_escape(stripped)
    user.premium_prefix = safe
    await session.flush()
    return True, f"✅ Префикс установлен: [{safe}]"


async def clear_prefix(session: AsyncSession, user_id: int) -> tuple[bool, str]:
    """Сбросить премиум-префикс (вернуть к дефолтному ⭐)."""
    result = await session.execute(
        select(User).where(User.tg_id == user_id).with_for_update()
    )
    user = result.scalar_one_or_none()
    if user is None:
        return False, "Пользователь не найден."

    user.premium_prefix = None
    await session.flush()
    return True, "✅ Префикс сброшен. Теперь отображается дефолтный ⭐."


async def get_prefix(session: AsyncSession, user_id: int) -> str:
    """Вернуть сохранённый префикс пользователя или пустую строку."""
    user = await _get_user(session, user_id)
    if user is None or user.premium_prefix is None:
        return ""
    return user.premium_prefix


def format_username(
    username: str,
    prefix: str | None,
    is_premium_active: bool = False,
) -> str:
    """
    Отформатировать имя игрока с учётом премиум-префикса.

    Логика:
      - Есть prefix и премиум активен → '[PREFIX] @username'
      - Нет prefix, но премиум активен → '@username ⭐'
      - Нет премиума → '@username'
    """
    if prefix and is_premium_active:
        return f"[{prefix}] {username}"
    if is_premium_active:
        return f"{username} ⭐"
    return username
