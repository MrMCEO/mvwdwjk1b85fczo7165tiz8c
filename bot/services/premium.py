"""
Premium subscription service — 5-level status system.

Statuses (ascending privilege order):
  FREE | BIO_PLUS | BIO_PRO | BIO_ELITE | BIO_LEGEND

BIO_LEGEND is obtained through referrals (50+), not purchased.
OWNER is a hidden developer-only status — never expose it in UI/listings.
All perk values live in STATUS_CONFIG — never hardcode them elsewhere.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime, timedelta
from html import escape as _html_escape

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.user import User

# ---------------------------------------------------------------------------
# Status enum & config
# ---------------------------------------------------------------------------

PREMIUM_DURATION_DAYS = 30

# Keep for backward compat with tests that import it directly
PREMIUM_COST = 200


class UserStatus(enum.Enum):
    FREE = "FREE"
    BIO_PLUS = "BIO_PLUS"
    BIO_PRO = "BIO_PRO"
    BIO_ELITE = "BIO_ELITE"
    BIO_LEGEND = "BIO_LEGEND"
    OWNER = "OWNER"


# ---------------------------------------------------------------------------
# Legacy premium config (pre-multi-tier, for rows that have premium_until set
# but status="FREE"). Exact values from the old PREMIUM_PERKS dict so existing
# tests continue to pass without modification.
# ---------------------------------------------------------------------------
_LEGACY_PREMIUM_CONFIG: dict = {
    "mining_bonus": 0.25,
    "daily_bonus": 0.50,
    "mining_cooldown": 45,
    "attack_cooldown": 25,
    "max_attempts_target": 4,
    "max_infections_hour": 6,
    "transfer_limit": 5000,
    "prefix_length": 5,
    "premium_emoji": True,
    "virus_name_length": 30,
}

# Sentinel used internally to indicate a legacy premium row
_LEGACY = "LEGACY"

# Ordered list for privilege comparisons (lowest → highest)
_STATUS_ORDER: list[UserStatus] = [
    UserStatus.FREE,
    UserStatus.BIO_PLUS,
    UserStatus.BIO_PRO,
    UserStatus.BIO_ELITE,
    UserStatus.BIO_LEGEND,
    UserStatus.OWNER,
]


STATUS_CONFIG: dict[UserStatus, dict] = {
    UserStatus.FREE: {
        "price": 0,
        "emoji": "",
        "name": "Бесплатный",
        "mining_bonus": 0.0,
        "daily_bonus": 0.0,
        "mining_cooldown": 60,
        "attack_cooldown": 30,
        "max_attempts_target": 3,
        "max_infections_hour": 5,
        "transfer_limit": 1500,
        "prefix_length": 0,
        "premium_emoji": False,
        "virus_name_length": 20,
    },
    UserStatus.BIO_PLUS: {
        "price": 100,
        "emoji": "🟢",
        "name": "Bio+",
        "mining_bonus": 0.10,
        "daily_bonus": 0.0,
        "mining_cooldown": 55,
        "attack_cooldown": 30,
        "max_attempts_target": 3,
        "max_infections_hour": 5,
        "transfer_limit": 3000,
        "prefix_length": 3,
        "premium_emoji": False,
        "virus_name_length": 25,
    },
    UserStatus.BIO_PRO: {
        "price": 200,
        "emoji": "🔵",
        "name": "Bio Pro",
        "mining_bonus": 0.20,
        "daily_bonus": 0.30,
        "mining_cooldown": 50,
        "attack_cooldown": 25,
        "max_attempts_target": 4,
        "max_infections_hour": 6,
        "transfer_limit": 5000,
        "prefix_length": 5,
        "premium_emoji": True,
        "virus_name_length": 30,
    },
    UserStatus.BIO_ELITE: {
        "price": 400,
        "emoji": "🟣",
        "name": "Bio Elite",
        "mining_bonus": 0.25,
        "daily_bonus": 0.50,
        "mining_cooldown": 45,
        "attack_cooldown": 25,
        "max_attempts_target": 5,
        "max_infections_hour": 7,
        "transfer_limit": 8000,
        "prefix_length": 5,
        "premium_emoji": True,
        "virus_name_length": 30,
    },
    UserStatus.BIO_LEGEND: {
        "price": 0,  # via referrals only
        "emoji": "👑",
        "name": "Bio Legend",
        "mining_bonus": 0.25,
        "daily_bonus": 0.50,
        "mining_cooldown": 45,
        "attack_cooldown": 25,
        "max_attempts_target": 5,
        "max_infections_hour": 7,
        "transfer_limit": 10000,
        "prefix_length": 5,
        "premium_emoji": True,
        "virus_name_length": 30,
    },
    UserStatus.OWNER: {
        "price": 0,  # admin-assigned only, permanent
        "emoji": "🔴",
        "name": "Owner",
        "hidden": True,  # never expose in UI/listings — developer-only status
        "mining_bonus": 0.25,
        "daily_bonus": 0.50,
        "mining_cooldown": 45,
        "attack_cooldown": 25,
        "max_attempts_target": 5,
        "max_infections_hour": 7,
        "transfer_limit": 999999,
        "prefix_length": 999,
        "premium_emoji": True,
        "virus_name_length": 999,
    },
}

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    """Return current naive UTC datetime (stored without tzinfo in DB)."""
    return datetime.now(UTC).replace(tzinfo=None)


async def _get_user(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(select(User).where(User.tg_id == user_id))
    return result.scalar_one_or_none()


def _parse_status(raw: str | None) -> UserStatus:
    """Safely parse a raw DB string to UserStatus, defaulting to FREE."""
    if raw is None:
        return UserStatus.FREE
    try:
        return UserStatus(raw)
    except ValueError:
        return UserStatus.FREE


def _status_gte(a: UserStatus, b: UserStatus) -> bool:
    """Return True if status *a* has equal or higher privilege than *b*."""
    return _STATUS_ORDER.index(a) >= _STATUS_ORDER.index(b)


def _is_legacy_premium(user: User) -> bool:
    """
    Return True for legacy rows: premium_until is active but status is still FREE.

    These are accounts created before the multi-tier system was introduced.
    """
    stored = _parse_status(getattr(user, "status", None))
    return (
        stored == UserStatus.FREE
        and user.premium_until is not None
        and user.premium_until > _now_utc()
    )


# ---------------------------------------------------------------------------
# Core status resolution
# ---------------------------------------------------------------------------


async def get_user_status(session: AsyncSession, user_id: int) -> UserStatus:
    """
    Determine the effective status for *user_id*.

    Rules:
      - BIO_LEGEND is permanent (set via referral system) — never expires.
      - All other paid statuses rely on premium_until not being in the past.
      - If premium_until has expired and status != BIO_LEGEND → effective status = FREE.
      - Legacy rows (premium_until active, status=FREE) are treated as BIO_ELITE for
        privilege-comparison purposes (>= BIO_PLUS check in is_premium() passes).
    """
    user = await _get_user(session, user_id)
    if user is None:
        return UserStatus.FREE

    stored = _parse_status(getattr(user, "status", None))

    # Legend and Owner are permanent (no expiry logic)
    if stored in (UserStatus.BIO_LEGEND, UserStatus.OWNER):
        return stored

    # For all paid statuses: check premium_until
    if stored != UserStatus.FREE:
        if user.premium_until is not None and user.premium_until > _now_utc():
            return stored
        # Subscription expired — fall back to FREE
        return UserStatus.FREE

    # Backward-compatibility: legacy rows have premium_until set but status="FREE"
    # Treat as BIO_ELITE so is_premium() returns True and privilege comparisons work.
    if _is_legacy_premium(user):
        return UserStatus.BIO_ELITE

    return UserStatus.FREE


async def _get_perk_config(session: AsyncSession, user_id: int) -> dict:
    """
    Return the perk config dict for *user_id*.

    For legacy rows (premium_until active, status=FREE) returns _LEGACY_PREMIUM_CONFIG,
    which preserves the exact old premium perk values (matching pre-migration tests).
    For all other users returns STATUS_CONFIG[effective_status].
    """
    user = await _get_user(session, user_id)
    if user is not None and _is_legacy_premium(user):
        return _LEGACY_PREMIUM_CONFIG
    status = await get_user_status(session, user_id)
    return STATUS_CONFIG[status]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def is_premium(session: AsyncSession, user_id: int) -> bool:
    """
    Return True if the user has an active paid subscription (>= BIO_PLUS).

    Kept for backward compatibility with all callers.
    """
    status = await get_user_status(session, user_id)
    return _status_gte(status, UserStatus.BIO_PLUS)


async def buy_status(
    session: AsyncSession, user_id: int, target: UserStatus
) -> tuple[bool, str]:
    """
    Purchase or extend *target* status for *user_id*.

    - BIO_LEGEND cannot be bought here (referral-only).
    - FREE cannot be bought (it's the default).
    - If the current status is different from target, subscription resets to now.
    - If the same status is already active, extends from current expiry.

    Returns (success, message).
    """
    if target in (UserStatus.FREE, UserStatus.BIO_LEGEND, UserStatus.OWNER):
        return False, "Этот статус нельзя купить напрямую."

    result = await session.execute(
        select(User).where(User.tg_id == user_id).with_for_update()
    )
    user = result.scalar_one_or_none()
    if user is None:
        return False, "Пользователь не найден."

    # Check hierarchy — cannot buy a status lower than current
    current = await get_user_status(session, user_id)
    if _status_gte(current, target) and current != target:
        current_cfg = STATUS_CONFIG[current]
        return False, (
            f"У тебя уже статус {current_cfg['emoji']} {current_cfg['name']}, "
            f"который выше или равен выбранному."
        )

    cfg = STATUS_CONFIG[target]
    cost: int = cfg["price"]

    if user.premium_coins < cost:
        return False, (
            f"Недостаточно 💎 PremiumCoins. Нужно {cost}, "
            f"у тебя {user.premium_coins}."
        )

    now = _now_utc()
    duration = timedelta(days=PREMIUM_DURATION_DAYS)

    stored = _parse_status(getattr(user, "status", None))
    current_active = (
        stored == target
        and user.premium_until is not None
        and user.premium_until > now
    )

    if current_active:
        new_until = user.premium_until + duration
        action = "продлена"
    else:
        new_until = now + duration
        action = "активирована"

    user.premium_coins -= cost
    user.premium_until = new_until
    user.status = target.value
    await session.flush()

    emoji = cfg["emoji"]
    name = cfg["name"]
    until_str = new_until.strftime("%d.%m.%Y")
    return True, (
        f"{emoji} Подписка «{name}» {action}! Действует до {until_str}.\n"
        f"Потрачено {cost} 💎 PremiumCoins."
    )


# Keep old buy_premium as an alias for BIO_PRO (backward compat)
async def buy_premium(session: AsyncSession, user_id: int) -> tuple[bool, str]:
    """
    Backward-compatible wrapper: buys/extends BIO_PRO subscription.

    Kept so existing call-sites don't break.
    """
    return await buy_status(session, user_id, UserStatus.BIO_PRO)


async def get_premium_info(session: AsyncSession, user_id: int) -> dict:
    """
    Return a dict with status info for *user_id*.

    Keys:
      is_active : bool          — True if any paid status is active
      status    : UserStatus    — the effective status
      until     : datetime|None — expiry datetime (naive UTC) or None
      days_left : int           — full days remaining (0 if not active)
    """
    user = await _get_user(session, user_id)
    status = await get_user_status(session, user_id)
    is_active = _status_gte(status, UserStatus.BIO_PLUS)

    if not is_active or user is None:
        return {
            "is_active": False,
            "status": status,
            "until": None,
            "days_left": 0,
        }

    # Legend and Owner have no expiry
    if status in (UserStatus.BIO_LEGEND, UserStatus.OWNER):
        return {
            "is_active": True,
            "status": status,
            "until": None,
            "days_left": 0,
        }

    now = _now_utc()
    until = user.premium_until
    days_left = max(0, (until - now).days) if until else 0
    return {
        "is_active": True,
        "status": status,
        "until": until,
        "days_left": days_left,
    }


# ---------------------------------------------------------------------------
# Perk getters — read from STATUS_CONFIG; keep same signatures as before
# ---------------------------------------------------------------------------


async def get_mining_cooldown(session: AsyncSession, user_id: int) -> timedelta:
    """Return mining cooldown as timedelta."""
    cfg = await _get_perk_config(session, user_id)
    return timedelta(minutes=cfg["mining_cooldown"])


async def get_attack_cooldown(session: AsyncSession, user_id: int) -> timedelta:
    """Return attack cooldown as timedelta."""
    cfg = await _get_perk_config(session, user_id)
    return timedelta(minutes=cfg["attack_cooldown"])


async def get_attack_limits(session: AsyncSession, user_id: int) -> tuple[int, int]:
    """Return (max_attempts_per_target, max_infections_per_hour)."""
    cfg = await _get_perk_config(session, user_id)
    return cfg["max_attempts_target"], cfg["max_infections_hour"]


async def get_virus_name_limit(session: AsyncSession, user_id: int) -> int:
    """Return max virus name length."""
    cfg = await _get_perk_config(session, user_id)
    return cfg["virus_name_length"]


async def get_mining_multiplier(session: AsyncSession, user_id: int) -> float:
    """Return mining yield multiplier (1.0 + mining_bonus)."""
    cfg = await _get_perk_config(session, user_id)
    return 1.0 + cfg["mining_bonus"]


async def get_daily_multiplier(session: AsyncSession, user_id: int) -> float:
    """Return daily bonus multiplier (1.0 + daily_bonus)."""
    cfg = await _get_perk_config(session, user_id)
    return 1.0 + cfg["daily_bonus"]


async def get_transfer_limit(session: AsyncSession, user_id: int) -> int:
    """Return maximum resource transfer limit for the user's status."""
    cfg = await _get_perk_config(session, user_id)
    return cfg["transfer_limit"]


async def can_use_premium_emoji(session: AsyncSession, user_id: int) -> bool:
    """Return True if the user's status allows premium emoji in virus names."""
    cfg = await _get_perk_config(session, user_id)
    return bool(cfg["premium_emoji"])


# ---------------------------------------------------------------------------
# Premium prefix
# ---------------------------------------------------------------------------

PREFIX_MAX_CHARS = 5


async def set_prefix(
    session: AsyncSession, user_id: int, prefix: str
) -> tuple[bool, str]:
    """
    Установить кастомный префикс.

    Доступен только если статус >= BIO_PLUS и prefix_length > 0 для статуса.
    Правила: не более PREFIX_MAX_CHARS видимых символов, не пустой.
    Применяется html.escape() для безопасности.

    Возвращает (success, message).
    """
    result = await session.execute(
        select(User).where(User.tg_id == user_id).with_for_update()
    )
    user = result.scalar_one_or_none()
    if user is None:
        return False, "Пользователь не найден."

    perk_cfg = await _get_perk_config(session, user_id)
    allowed_len = perk_cfg["prefix_length"]
    if allowed_len == 0:
        return False, "❌ Кастомный префикс доступен только для премиум-подписчиков."

    stripped = prefix.strip()
    if not stripped:
        return False, "❌ Префикс не может быть пустым."
    if len(stripped) > allowed_len:
        return False, (
            f"❌ Префикс слишком длинный. Максимум {allowed_len} символов для твоего статуса, "
            f"у тебя {len(stripped)}."
        )

    safe = _html_escape(stripped)
    # Guard against escaped string overflowing the DB column (5 raw chars can
    # produce up to 30 escaped chars for worst-case HTML entities like &amp;).
    # The User.premium_prefix column is String(30) to accommodate this.
    if len(safe) > 30:
        return False, "❌ Префикс содержит слишком много специальных символов."

    # Uniqueness check — no two players can have the same prefix
    existing = await session.execute(
        select(User.tg_id).where(User.premium_prefix == safe, User.tg_id != user_id)
    )
    if existing.scalar_one_or_none() is not None:
        return False, "❌ Этот префикс уже занят другим игроком."

    user.premium_prefix = safe
    await session.flush()
    return True, f"✅ Префикс установлен: [{safe}]"


async def clear_prefix(session: AsyncSession, user_id: int) -> tuple[bool, str]:
    """Сбросить премиум-префикс."""
    result = await session.execute(
        select(User).where(User.tg_id == user_id).with_for_update()
    )
    user = result.scalar_one_or_none()
    if user is None:
        return False, "Пользователь не найден."

    user.premium_prefix = None
    await session.flush()
    return True, "✅ Префикс сброшен."


async def get_prefix(session: AsyncSession, user_id: int) -> str:
    """Вернуть сохранённый префикс пользователя или пустую строку."""
    user = await _get_user(session, user_id)
    if user is None or user.premium_prefix is None:
        return ""
    return user.premium_prefix


def format_username(
    base_username: str,
    prefix: str | None = None,
    is_premium_active: bool = False,
    display_name: str | None = None,
    status_emoji: str = "",
) -> str:
    """
    Отформатировать имя игрока с учётом display_name, статуса и префикса.

    Логика:
      - Если display_name задан — используется вместо @username
      - Есть prefix и есть статус → '[PREFIX] имя'
      - Нет prefix, но есть статус → 'имя {status_emoji}'
        (например 'имя 🔵' или 'имя ⭐' для совместимости)
      - Нет статуса → 'имя'

    Параметр *is_premium_active* оставлен для обратной совместимости.
    Если *status_emoji* не передан, но *is_premium_active* True — используется '⭐'.
    """
    name = display_name if display_name else base_username
    effective_emoji = status_emoji or ("⭐" if is_premium_active else "")

    if prefix and (is_premium_active or effective_emoji):
        return f"[{prefix}] {name}"
    if effective_emoji:
        return f"{name} {effective_emoji}"
    return name


# ---------------------------------------------------------------------------
# Display name (доступно всем игрокам)
# ---------------------------------------------------------------------------

DISPLAY_NAME_MAX_CHARS = 20


async def set_display_name(
    session: AsyncSession, user_id: int, name: str
) -> tuple[bool, str]:
    """
    Установить кастомное отображаемое имя (до 20 символов). Доступно всем.

    Применяется html.escape() для безопасности.
    Возвращает (success, message).
    """
    result = await session.execute(
        select(User).where(User.tg_id == user_id).with_for_update()
    )
    user = result.scalar_one_or_none()
    if user is None:
        return False, "Пользователь не найден."

    stripped = name.strip()
    if not stripped:
        return False, "❌ Имя не может быть пустым."
    if len(stripped) > DISPLAY_NAME_MAX_CHARS:
        return False, (
            f"❌ Имя слишком длинное. Максимум {DISPLAY_NAME_MAX_CHARS} символов, "
            f"у тебя {len(stripped)}."
        )

    safe = _html_escape(stripped)
    # Guard against escaped string overflowing the DB column (20 raw chars can
    # produce up to 120 escaped chars for worst-case HTML entities like &amp;).
    # The User.display_name column is String(120) to accommodate this.
    if len(safe) > 120:
        return False, "❌ Имя содержит слишком много специальных символов."
    user.display_name = safe
    await session.flush()
    return True, f"✅ Отображаемое имя установлено: <b>{safe}</b>"


async def clear_display_name(session: AsyncSession, user_id: int) -> tuple[bool, str]:
    """Сбросить кастомное имя (вернуть отображение @username)."""
    result = await session.execute(
        select(User).where(User.tg_id == user_id).with_for_update()
    )
    user = result.scalar_one_or_none()
    if user is None:
        return False, "Пользователь не найден."

    user.display_name = None
    await session.flush()
    return True, "✅ Отображаемое имя сброшено. Теперь показывается @username."
