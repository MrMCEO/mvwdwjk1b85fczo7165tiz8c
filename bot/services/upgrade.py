"""
Upgrade service — virus and immunity branch levelling.

Upgrade cost formula:  int(base_cost * (multiplier ** current_level))
  current_level == 0  → cost equals base_cost  (buying level 1)
  current_level == 1  → cost is base_cost * multiplier  (buying level 2)
  …and so on.

Each branch is stored as a VirusUpgrade / ImmunityUpgrade row.
When no row exists yet the branch is implicitly at level 0, effect_value 0.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.immunity import Immunity, ImmunityBranch, ImmunityUpgrade
from bot.models.resource import (
    Currency as CurrencyType,
)
from bot.models.resource import (
    ResourceTransaction,
    TransactionReason,
)
from bot.models.user import User
from bot.models.virus import Virus, VirusBranch, VirusUpgrade
from bot.services.referral import check_qualification, update_referral_activity

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

UPGRADE_CONFIG: dict[str, dict[str, dict]] = {
    "virus": {
        # LETHALITY: +2 damage_per_tick per level. Lvl10 = +20 dmg (total 25 with base 5).
        # Old 5.0 was OP — lvl10 gave +50 dmg, wiping daily income in 5hrs.
        "LETHALITY": {"base_cost": 80, "multiplier": 1.25, "base_effect": 2.0},
        # CONTAGION: +0.08 multiplier to attack_score per level. Lvl10 = +80% attack.
        # Old 0.05 was too weak vs BARRIER. Now meaningful but not dominant.
        "CONTAGION": {"base_cost": 80, "multiplier": 1.25, "base_effect": 0.08},
        # STEALTH: -0.05 effective detection per level. Now works across 20 lvls.
        # Old 0.1 fully negated detection at lvl1 (detection default was 0.1). Fixed.
        "STEALTH":   {"base_cost": 90, "multiplier": 1.25, "base_effect": 0.05},
    },
    "immunity": {
        # BARRIER: +3 flat defense_score per level (ADDITIVE, not multiplicative).
        # Old 5.0 was multiplied by resistance, giving 510 defense at lvl10 — game-breaking.
        # Now lvl10 = +30 defense. See combat.py formula change.
        "BARRIER":       {"base_cost": 80, "multiplier": 1.25, "base_effect": 3.0},
        # DETECTION: +0.05 detection_power per level. Lvl10 = +0.5 detection.
        # Old 0.1 was either too much (overshadowed by stealth) or negligible in formula.
        "DETECTION":     {"base_cost": 80, "multiplier": 1.25, "base_effect": 0.05},
        # REGENERATION: +0.02 auto-cure chance per level. Lvl10 = +20% auto-cure.
        # Old 0.05 subtracted from damage — at lvl10 only -0.5 dmg, useless.
        # Now directly boosts recovery_speed used in auto-cure rolls.
        "REGENERATION":  {"base_cost": 90, "multiplier": 1.25, "base_effect": 0.02},
    },
}

# Human-readable branch names
_VIRUS_BRANCH_NAMES = {
    "LETHALITY": "Летальность",
    "CONTAGION":  "Заразность",
    "STEALTH":    "Скрытность",
}

_IMMUNITY_BRANCH_NAMES = {
    "BARRIER":      "Барьер",
    "DETECTION":    "Детекция",
    "REGENERATION": "Регенерация",
}

# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def calc_upgrade_cost(base_cost: int, multiplier: float, current_level: int) -> int:
    """
    Return the bio_coins cost of upgrading from *current_level* to current_level+1.

    Examples
    --------
    >>> calc_upgrade_cost(100, 1.5, 0)   # buy level 1
    100
    >>> calc_upgrade_cost(100, 1.5, 1)   # buy level 2
    150
    >>> calc_upgrade_cost(100, 1.5, 3)   # buy level 4
    337
    """
    return int(base_cost * (multiplier ** current_level))


# ---------------------------------------------------------------------------
# Internal DB helpers
# ---------------------------------------------------------------------------


async def _get_user(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(
        select(User).where(User.tg_id == user_id).with_for_update()
    )
    return result.scalar_one_or_none()


async def _get_virus(session: AsyncSession, user_id: int) -> Virus | None:
    result = await session.execute(select(Virus).where(Virus.owner_id == user_id))
    return result.scalar_one_or_none()


async def _get_immunity(session: AsyncSession, user_id: int) -> Immunity | None:
    result = await session.execute(
        select(Immunity).where(Immunity.owner_id == user_id)
    )
    return result.scalar_one_or_none()


async def _get_virus_upgrade(
    session: AsyncSession, virus_id: int, branch: VirusBranch
) -> VirusUpgrade | None:
    result = await session.execute(
        select(VirusUpgrade).where(
            VirusUpgrade.virus_id == virus_id,
            VirusUpgrade.branch == branch,
        )
    )
    return result.scalar_one_or_none()


async def _get_immunity_upgrade(
    session: AsyncSession, immunity_id: int, branch: ImmunityBranch
) -> ImmunityUpgrade | None:
    result = await session.execute(
        select(ImmunityUpgrade).where(
            ImmunityUpgrade.immunity_id == immunity_id,
            ImmunityUpgrade.branch == branch,
        )
    )
    return result.scalar_one_or_none()


def _validate_branch(
    tree: str, branch: str
) -> tuple[bool, str]:
    """Return (ok, error_message). ok=True means branch name is valid for tree."""
    valid = UPGRADE_CONFIG.get(tree, {})
    if branch.upper() not in valid:
        names = ", ".join(valid.keys())
        return False, f"Неизвестная ветка '{branch}'. Доступные: {names}."
    return True, ""


# ---------------------------------------------------------------------------
# Virus upgrades
# ---------------------------------------------------------------------------


async def upgrade_virus_branch(
    session: AsyncSession,
    user_id: int,
    branch: str,
) -> tuple[bool, str]:
    """
    Upgrade a virus branch by one level for *user_id*.

    Returns (success, message).
    """
    branch_key = branch.upper()
    ok, err = _validate_branch("virus", branch_key)
    if not ok:
        return False, err

    user = await _get_user(session, user_id)
    if user is None:
        return False, "Пользователь не найден."

    virus = await _get_virus(session, user_id)
    if virus is None:
        return False, "У тебя ещё нет вируса. Создай его сначала."

    virus_branch_enum = VirusBranch[branch_key]
    upgrade = await _get_virus_upgrade(session, virus.id, virus_branch_enum)

    current_level = upgrade.level if upgrade is not None else 0

    cfg = UPGRADE_CONFIG["virus"][branch_key]
    cost = calc_upgrade_cost(cfg["base_cost"], cfg["multiplier"], current_level)

    if user.bio_coins < cost:
        return False, (
            f"Недостаточно 🧫 BioCoins. Нужно {cost}, у тебя {user.bio_coins}."
        )

    # Deduct coins
    user.bio_coins -= cost

    # Apply upgrade
    new_effect = cfg["base_effect"] * (current_level + 1)
    if upgrade is None:
        upgrade = VirusUpgrade(
            virus_id=virus.id,
            branch=virus_branch_enum,
            level=1,
            effect_value=new_effect,
        )
        session.add(upgrade)
    else:
        upgrade.level += 1
        upgrade.effect_value = cfg["base_effect"] * upgrade.level

    # Record transaction
    tx = ResourceTransaction(
        user_id=user_id,
        amount=-cost,
        currency=CurrencyType.BIO_COINS,
        reason=TransactionReason.UPGRADE,
    )
    session.add(tx)
    await session.flush()

    # Пересчитать уровень вируса = сумма уровней всех веток
    all_upgrades = await session.execute(
        select(VirusUpgrade).where(VirusUpgrade.virus_id == virus.id)
    )
    virus.level = sum(u.level for u in all_upgrades.scalars().all())

    # Реферальная программа: обновить активность и проверить квалификацию
    await update_referral_activity(session, user_id)
    await check_qualification(session, user_id)

    branch_name = _VIRUS_BRANCH_NAMES[branch_key]
    new_level = upgrade.level
    next_cost = calc_upgrade_cost(cfg["base_cost"], cfg["multiplier"], new_level)
    return True, (
        f"Ветка «{branch_name}» прокачана до уровня {new_level}! "
        f"Эффект: {upgrade.effect_value:.2f}. "
        f"Потрачено: {cost} 🧫 BioCoins. Следующий уровень: {next_cost} 🧫 BioCoins."
    )


# ---------------------------------------------------------------------------
# Immunity upgrades
# ---------------------------------------------------------------------------


async def upgrade_immunity_branch(
    session: AsyncSession,
    user_id: int,
    branch: str,
) -> tuple[bool, str]:
    """
    Upgrade an immunity branch by one level for *user_id*.

    Returns (success, message).
    """
    branch_key = branch.upper()
    ok, err = _validate_branch("immunity", branch_key)
    if not ok:
        return False, err

    user = await _get_user(session, user_id)
    if user is None:
        return False, "Пользователь не найден."

    immunity = await _get_immunity(session, user_id)
    if immunity is None:
        return False, "У тебя ещё нет иммунитета. Создай его сначала."

    immunity_branch_enum = ImmunityBranch[branch_key]
    upgrade = await _get_immunity_upgrade(session, immunity.id, immunity_branch_enum)

    current_level = upgrade.level if upgrade is not None else 0

    cfg = UPGRADE_CONFIG["immunity"][branch_key]
    cost = calc_upgrade_cost(cfg["base_cost"], cfg["multiplier"], current_level)

    if user.bio_coins < cost:
        return False, (
            f"Недостаточно 🧫 BioCoins. Нужно {cost}, у тебя {user.bio_coins}."
        )

    # Deduct coins
    user.bio_coins -= cost

    # Apply upgrade
    new_effect = cfg["base_effect"] * (current_level + 1)
    if upgrade is None:
        upgrade = ImmunityUpgrade(
            immunity_id=immunity.id,
            branch=immunity_branch_enum,
            level=1,
            effect_value=new_effect,
        )
        session.add(upgrade)
    else:
        upgrade.level += 1
        upgrade.effect_value = cfg["base_effect"] * upgrade.level

    # Record transaction
    tx = ResourceTransaction(
        user_id=user_id,
        amount=-cost,
        currency=CurrencyType.BIO_COINS,
        reason=TransactionReason.UPGRADE,
    )
    session.add(tx)
    await session.flush()

    # Пересчитать уровень иммунитета = сумма уровней всех веток
    all_imm_upgrades = await session.execute(
        select(ImmunityUpgrade).where(ImmunityUpgrade.immunity_id == immunity.id)
    )
    immunity.level = sum(u.level for u in all_imm_upgrades.scalars().all())

    # Реферальная программа: обновить активность и проверить квалификацию
    await update_referral_activity(session, user_id)
    await check_qualification(session, user_id)

    branch_name = _IMMUNITY_BRANCH_NAMES[branch_key]
    new_level = upgrade.level
    next_cost = calc_upgrade_cost(cfg["base_cost"], cfg["multiplier"], new_level)
    return True, (
        f"Ветка «{branch_name}» прокачана до уровня {new_level}! "
        f"Эффект: {upgrade.effect_value:.2f}. "
        f"Потрачено: {cost} 🧫 BioCoins. Следующий уровень: {next_cost} 🧫 BioCoins."
    )


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


async def get_virus_stats(session: AsyncSession, user_id: int) -> dict:
    """
    Return full information about the user's virus and its upgrades.

    Keys
    ----
    virus     : dict with id, name, level, attack_power, spread_rate, mutation_points
    upgrades  : dict branch_key → {level, effect_value, next_cost}
    error     : str (only present when virus not found)
    """
    virus = await _get_virus(session, user_id)
    if virus is None:
        return {"error": "Вирус не найден."}

    # Load all upgrades for this virus
    result = await session.execute(
        select(VirusUpgrade).where(VirusUpgrade.virus_id == virus.id)
    )
    upgrades_rows = result.scalars().all()
    upgrades_by_branch: dict[str, VirusUpgrade] = {
        row.branch.value: row for row in upgrades_rows
    }

    upgrades: dict[str, dict] = {}
    for branch_key, cfg in UPGRADE_CONFIG["virus"].items():
        row = upgrades_by_branch.get(branch_key)
        current_level = row.level if row is not None else 0
        effect_value = row.effect_value if row is not None else 0.0
        next_cost = calc_upgrade_cost(cfg["base_cost"], cfg["multiplier"], current_level)
        upgrades[branch_key] = {
            "name": _VIRUS_BRANCH_NAMES[branch_key],
            "level": current_level,
            "effect_value": effect_value,
            "next_cost": next_cost,
        }

    return {
        "virus": {
            "id": virus.id,
            "name": virus.name,
            "name_entities_json": virus.name_entities_json,
            "level": virus.level,
            "attack_power": virus.attack_power,
            "spread_rate": virus.spread_rate,
            "mutation_points": virus.mutation_points,
        },
        "upgrades": upgrades,
    }


async def get_immunity_stats(session: AsyncSession, user_id: int) -> dict:
    """
    Return full information about the user's immunity and its upgrades.

    Keys
    ----
    immunity  : dict with id, level, resistance, detection_power, recovery_speed
    upgrades  : dict branch_key → {level, effect_value, next_cost}
    error     : str (only present when immunity not found)
    """
    immunity = await _get_immunity(session, user_id)
    if immunity is None:
        return {"error": "Иммунитет не найден."}

    result = await session.execute(
        select(ImmunityUpgrade).where(ImmunityUpgrade.immunity_id == immunity.id)
    )
    upgrades_rows = result.scalars().all()
    upgrades_by_branch: dict[str, ImmunityUpgrade] = {
        row.branch.value: row for row in upgrades_rows
    }

    upgrades: dict[str, dict] = {}
    for branch_key, cfg in UPGRADE_CONFIG["immunity"].items():
        row = upgrades_by_branch.get(branch_key)
        current_level = row.level if row is not None else 0
        effect_value = row.effect_value if row is not None else 0.0
        next_cost = calc_upgrade_cost(cfg["base_cost"], cfg["multiplier"], current_level)
        upgrades[branch_key] = {
            "name": _IMMUNITY_BRANCH_NAMES[branch_key],
            "level": current_level,
            "effect_value": effect_value,
            "next_cost": next_cost,
        }

    return {
        "immunity": {
            "id": immunity.id,
            "level": immunity.level,
            "resistance": immunity.resistance,
            "detection_power": immunity.detection_power,
            "recovery_speed": immunity.recovery_speed,
        },
        "upgrades": upgrades,
    }
