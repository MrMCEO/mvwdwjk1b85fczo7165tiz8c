"""
Laboratory service — crafting items and managing player inventory.

Flow:
  - craft_item: check balance → deduct bio_coins → create Item → log transaction
  - get_inventory: return unused items grouped by type
  - use_item: validate ownership → apply effect → mark used
  - get_active_item_effect: check if a timed effect is currently active
  - spy_on_player: retrieve full stats of a target by username
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.models.immunity import Immunity
from bot.models.infection import Infection
from bot.models.item import ITEM_CONFIG, Item, ItemType
from bot.models.mutation import Mutation, MutationRarity
from bot.models.resource import Currency, ResourceTransaction, TransactionReason
from bot.models.user import User
from bot.models.virus import Virus
from bot.services.mutation import _TYPES_BY_RARITY, MUTATION_CONFIG, RARITY_WEIGHTS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _get_user(session: AsyncSession, user_id: int) -> User | None:
    result = await session.execute(
        select(User).where(User.tg_id == user_id).with_for_update()
    )
    return result.scalar_one_or_none()


_RARITY_LABELS: dict[MutationRarity, str] = {
    MutationRarity.COMMON: "Обычная",
    MutationRarity.UNCOMMON: "Необычная",
    MutationRarity.RARE: "Редкая",
    MutationRarity.LEGENDARY: "Легендарная",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def craft_item(
    session: AsyncSession,
    user_id: int,
    item_type: ItemType,
) -> tuple[bool, str]:
    """
    Craft an item for *user_id* by spending bio_coins.

    Returns (success, message).
    """
    cfg = ITEM_CONFIG[item_type]
    cost: int = cfg["cost"]
    name: str = cfg["name"]
    emoji: str = cfg["emoji"]

    user = await _get_user(session, user_id)
    if user is None:
        return False, "Игрок не найден."

    if user.bio_coins < cost:
        shortage = cost - user.bio_coins
        return False, (
            f"Недостаточно 🧫 BioCoins!\n"
            f"Нужно: <b>{cost}</b> 🧫 BioCoins\n"
            f"У тебя: <b>{user.bio_coins}</b> 🧫 BioCoins\n"
            f"Не хватает: <b>{shortage}</b> 🧫 BioCoins"
        )

    # Списать монеты
    user.bio_coins -= cost

    # Создать предмет
    item = Item(
        owner_id=user_id,
        item_type=item_type,
    )
    session.add(item)

    # Записать транзакцию
    tx = ResourceTransaction(
        user_id=user_id,
        amount=-cost,
        currency=Currency.BIO_COINS,
        reason=TransactionReason.UPGRADE,
    )
    session.add(tx)

    await session.flush()

    return True, (
        f"{emoji} <b>{name}</b> успешно скрафчен!\n"
        f"Потрачено: <b>{cost}</b> 🧫 BioCoins\n"
        f"Баланс: <b>{user.bio_coins}</b> 🧫 BioCoins\n\n"
        "Предмет добавлен в инвентарь."
    )


async def get_inventory(session: AsyncSession, user_id: int) -> list[dict]:
    """
    Return unused items grouped by type with counts.

    Each dict:
      {item_type, name, emoji, desc, count, item_ids: list[int]}
    """
    result = await session.execute(
        select(Item)
        .where(
            and_(
                Item.owner_id == user_id,
                Item.is_used == False,  # noqa: E712
            )
        )
        .order_by(Item.item_type, Item.created_at)
    )
    items = list(result.scalars().all())

    # Group by type
    groups: dict[ItemType, list[Item]] = {}
    for item in items:
        groups.setdefault(item.item_type, []).append(item)

    inventory: list[dict] = []
    for item_type, group in groups.items():
        cfg = ITEM_CONFIG[item_type]
        inventory.append(
            {
                "item_type": item_type,
                "name": cfg["name"],
                "emoji": cfg["emoji"],
                "desc": cfg["desc"],
                "count": len(group),
                # First item id is used for "use" button
                "item_ids": [i.id for i in group],
            }
        )

    return inventory


async def use_item(
    session: AsyncSession,
    user_id: int,
    item_id: int,
) -> tuple[bool, str, dict]:
    """
    Use an item from inventory.

    Returns (success, message, extra_data).
    extra_data may contain:
      - {"type": "combat_buff", "item_type": "...", "item_id": ...} for combat items
      - {"type": "spy", "needs_target": True, "item_id": ...} for SPY_DRONE
      - {} for items that are fully handled here
    """
    result = await session.execute(
        select(Item)
        .where(
            and_(
                Item.id == item_id,
                Item.owner_id == user_id,
                Item.is_used == False,  # noqa: E712
            )
        )
        .with_for_update()
    )
    item = result.scalar_one_or_none()

    if item is None:
        return False, "Предмет не найден или уже использован.", {}

    cfg = ITEM_CONFIG[item.item_type]
    name: str = cfg["name"]
    emoji: str = cfg["emoji"]
    now = _now_utc()

    # -----------------------------------------------------------------------
    # Apply effect by item type
    # -----------------------------------------------------------------------

    if item.item_type == ItemType.VACCINE:
        # Излечить самое новое заражение
        inf_result = await session.execute(
            select(Infection)
            .where(
                and_(
                    Infection.victim_id == user_id,
                    Infection.is_active == True,  # noqa: E712
                )
            )
            .order_by(Infection.started_at.desc())
            .limit(1)
            .with_for_update()
        )
        infection = inf_result.scalar_one_or_none()
        if infection is None:
            return False, "Нет активных заражений — вакцина не нужна.", {}
        infection.is_active = False
        _mark_used(item, now)
        await session.flush()
        return True, (
            f"{emoji} <b>{name}</b> использована!\n"
            "Одно заражение излечено."
        ), {}

    elif item.item_type == ItemType.ANTIDOTE:
        # Излечить ВСЕ заражения
        inf_result = await session.execute(
            select(Infection)
            .where(
                and_(
                    Infection.victim_id == user_id,
                    Infection.is_active == True,  # noqa: E712
                )
            )
            .with_for_update()
        )
        infections = list(inf_result.scalars().all())
        if not infections:
            return False, "Нет активных заражений — антидот не нужен.", {}
        for inf in infections:
            inf.is_active = False
        _mark_used(item, now)
        await session.flush()
        return True, (
            f"{emoji} <b>{name}</b> использован!\n"
            f"Излечено заражений: <b>{len(infections)}</b>."
        ), {}

    elif item.item_type == ItemType.SHIELD_BOOST:
        # +50% защиты на 2 часа
        item.effect_expires_at = now + timedelta(hours=2)
        item.is_used = True
        item.used_at = now
        await session.flush()
        return True, (
            f"{emoji} <b>{name}</b> активирован!\n"
            "+50% к защите на <b>2 часа</b>."
        ), {}

    elif item.item_type == ItemType.RESOURCE_BOOSTER:
        # x2 добыча на 3 часа
        item.effect_expires_at = now + timedelta(hours=3)
        item.is_used = True
        item.used_at = now
        await session.flush()
        return True, (
            f"{emoji} <b>{name}</b> активирован!\n"
            "x2 к добыче ресурсов на <b>3 часа</b>."
        ), {}

    elif item.item_type in (ItemType.BIO_BOMB, ItemType.VIRUS_ENHANCER, ItemType.STEALTH_CLOAK):
        # Боевые баффы — пометить, вернуть данные для будущей интеграции
        _mark_used(item, now)
        await session.flush()
        return True, (
            f"{emoji} <b>{name}</b> готов к применению!\n"
            f"{cfg['desc']}\n\n"
            "<i>Бафф будет применён при следующей атаке.</i>"
        ), {"type": "combat_buff", "item_type": item.item_type.value, "item_id": item_id}

    elif item.item_type == ItemType.LUCKY_CHARM:
        # x3 к ежедневному бонусу — отмечаем использование
        _mark_used(item, now)
        await session.flush()
        return True, (
            f"{emoji} <b>{name}</b> активирован!\n"
            "Следующий ежедневный бонус будет x3!"
        ), {}

    elif item.item_type == ItemType.SPY_DRONE:
        # Нужна цель — не помечаем использованным сразу, ждём ввода username
        return True, (
            f"{emoji} <b>{name}</b> готов!\n"
            "Введи @username или имя пользователя цели:"
        ), {"type": "spy", "needs_target": True, "item_id": item_id}

    elif item.item_type == ItemType.MUTATION_SERUM:
        # Гарантированная мутация
        rarities = list(RARITY_WEIGHTS.keys())
        weights = [RARITY_WEIGHTS[r] for r in rarities]
        chosen_rarity: MutationRarity = random.choices(rarities, weights=weights, k=1)[0]
        candidates = _TYPES_BY_RARITY.get(chosen_rarity, [])
        if not candidates:
            return False, "Ошибка при применении сыворотки.", {}
        chosen_type = random.choice(candidates)
        cfg_m = MUTATION_CONFIG[chosen_type]

        mutation = Mutation(
            owner_id=user_id,
            mutation_type=chosen_type,
            rarity=chosen_rarity,
            effect_value=cfg_m["effect"],
            duration_hours=cfg_m["duration"],
            activated_at=now,
            is_active=True,
            is_used=False,
        )
        session.add(mutation)
        _mark_used(item, now)
        await session.flush()

        rarity_label = _RARITY_LABELS.get(chosen_rarity, chosen_rarity.value)

        return True, (
            f"{emoji} <b>Сыворотка мутации</b> использована!\n\n"
            f"Получена мутация: <b>{chosen_type.value}</b>\n"
            f"Редкость: <b>{rarity_label}</b>\n"
            f"Эффект: {cfg_m['description']}"
        ), {}

    # Неизвестный тип (на всякий случай)
    _mark_used(item, now)
    await session.flush()
    return True, f"{emoji} <b>{name}</b> использован.", {}


def _mark_used(item: Item, now: datetime) -> None:
    item.is_used = True
    item.used_at = now


async def get_active_item_effect(
    session: AsyncSession,
    user_id: int,
    item_type: ItemType,
) -> bool:
    """
    Return True if there is an active (not yet expired) timed effect
    of *item_type* for *user_id*.

    Applicable types: SHIELD_BOOST, RESOURCE_BOOSTER.
    For non-timed types always returns False.
    """
    now = _now_utc()
    result = await session.execute(
        select(Item).where(
            and_(
                Item.owner_id == user_id,
                Item.item_type == item_type,
                Item.is_used == True,  # noqa: E712
                Item.effect_expires_at > now,
            )
        ).limit(1)
    )
    return result.scalar_one_or_none() is not None


async def spy_on_player(
    session: AsyncSession,
    target_username: str,
) -> dict | None:
    """
    Return full stats of a target player by username (without leading @).

    Returns None if player not found.
    """
    clean = target_username.lstrip("@").strip()

    result = await session.execute(
        select(User)
        .where(func.lower(User.username) == clean.lower())
        .options(
            selectinload(User.virus).selectinload(Virus.upgrades),
            selectinload(User.immunity).selectinload(Immunity.upgrades),
        )
    )
    user = result.scalar_one_or_none()
    if user is None:
        return None

    # Virus data
    virus_data: dict = {}
    if user.virus is not None:
        v = user.virus
        upgrades: dict[str, dict] = {}
        for u in v.upgrades:
            upgrades[u.branch.value] = {"level": u.level, "effect_value": u.effect_value}
        virus_data = {
            "name": v.name,
            "level": v.level,
            "attack_power": v.attack_power,
            "spread_rate": v.spread_rate,
            "mutation_points": v.mutation_points,
            "upgrades": upgrades,
        }

    # Immunity data
    immunity_data: dict = {}
    if user.immunity is not None:
        im = user.immunity
        im_upgrades: dict[str, dict] = {}
        for u in im.upgrades:
            im_upgrades[u.branch.value] = {"level": u.level, "effect_value": u.effect_value}
        immunity_data = {
            "level": im.level,
            "resistance": im.resistance,
            "detection_power": im.detection_power,
            "recovery_speed": im.recovery_speed,
            "upgrades": im_upgrades,
        }

    # Active infections count
    inf_result = await session.execute(
        select(func.count(Infection.id)).where(
            and_(
                Infection.victim_id == user.tg_id,
                Infection.is_active == True,  # noqa: E712
            )
        )
    )
    active_infections: int = inf_result.scalar_one()

    return {
        "tg_id": user.tg_id,
        "username": user.username,
        "bio_coins": user.bio_coins,
        "virus": virus_data,
        "immunity": immunity_data,
        "active_infections": active_infections,
    }
