"""
Unit tests for bot/services/laboratory.py
"""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.models.infection import Infection
from bot.models.item import ITEM_CONFIG, ItemType
from bot.models.user import User
from bot.services.laboratory import craft_item, get_inventory, use_item
from bot.services.player import create_player


async def _give_coins(session: AsyncSession, tg_id: int, amount: int) -> None:
    result = await session.execute(select(User).where(User.tg_id == tg_id))
    user = result.scalar_one()
    user.bio_coins = amount
    await session.flush()


async def test_craft_item(session: AsyncSession):
    """Crafting a VACCINE succeeds and deducts bio_coins."""
    await create_player(session, tg_id=7001, username="crafter1")
    cost = ITEM_CONFIG[ItemType.VACCINE]["cost"]
    await _give_coins(session, 7001, cost + 100)

    ok, msg = await craft_item(session, user_id=7001, item_type=ItemType.VACCINE)
    assert ok is True
    assert "Вакцина" in msg or "скрафчен" in msg

    # Check balance reduced
    result = await session.execute(select(User).where(User.tg_id == 7001))
    user = result.scalar_one()
    assert user.bio_coins == 100


async def test_craft_not_enough_coins(session: AsyncSession):
    """Crafting without enough coins fails gracefully."""
    await create_player(session, tg_id=7002, username="crafter2")
    # Leave bio_coins at 0

    ok, msg = await craft_item(session, user_id=7002, item_type=ItemType.ANTIDOTE)
    assert ok is False
    assert "Недостаточно" in msg


async def test_craft_multiple_items(session: AsyncSession):
    """Crafting two different items creates two inventory entries."""
    await create_player(session, tg_id=7003, username="crafter3")
    cost_v = ITEM_CONFIG[ItemType.VACCINE]["cost"]
    cost_r = ITEM_CONFIG[ItemType.RESOURCE_BOOSTER]["cost"]
    await _give_coins(session, 7003, cost_v + cost_r + 100)

    await craft_item(session, user_id=7003, item_type=ItemType.VACCINE)
    await craft_item(session, user_id=7003, item_type=ItemType.RESOURCE_BOOSTER)

    inventory = await get_inventory(session, user_id=7003)
    item_types = {entry["item_type"] for entry in inventory}
    assert ItemType.VACCINE in item_types
    assert ItemType.RESOURCE_BOOSTER in item_types


async def test_use_vaccine(session: AsyncSession):
    """Using VACCINE cures an active infection."""
    await create_player(session, tg_id=7010, username="patient10")
    await create_player(session, tg_id=7011, username="attacker11")

    # Give player a vaccine
    cost = ITEM_CONFIG[ItemType.VACCINE]["cost"]
    await _give_coins(session, 7010, cost)
    await craft_item(session, user_id=7010, item_type=ItemType.VACCINE)

    # Create an active infection on player 7010
    infection = Infection(
        attacker_id=7011,
        victim_id=7010,
        is_active=True,
    )
    session.add(infection)
    await session.flush()

    # Get the item id
    inventory = await get_inventory(session, user_id=7010)
    assert len(inventory) == 1
    item_id = inventory[0]["item_ids"][0]

    ok, msg, _ = await use_item(session, user_id=7010, item_id=item_id)
    assert ok is True
    assert "излечено" in msg.lower() or "Вакцина" in msg

    # Check infection is deactivated
    await session.refresh(infection)
    assert infection.is_active is False


async def test_use_vaccine_no_infection(session: AsyncSession):
    """Using VACCINE when not infected returns failure."""
    await create_player(session, tg_id=7020, username="healthy20")
    cost = ITEM_CONFIG[ItemType.VACCINE]["cost"]
    await _give_coins(session, 7020, cost)
    await craft_item(session, user_id=7020, item_type=ItemType.VACCINE)

    inventory = await get_inventory(session, user_id=7020)
    item_id = inventory[0]["item_ids"][0]

    ok, msg, _ = await use_item(session, user_id=7020, item_id=item_id)
    assert ok is False
    assert "не нужна" in msg or "нет активных" in msg.lower()


async def test_get_inventory_empty(session: AsyncSession):
    """get_inventory returns empty list when player has no items."""
    await create_player(session, tg_id=7030, username="empty30")
    inventory = await get_inventory(session, user_id=7030)
    assert inventory == []


async def test_get_inventory_shows_crafted(session: AsyncSession):
    """get_inventory shows newly crafted items."""
    await create_player(session, tg_id=7040, username="inv40")
    cost = ITEM_CONFIG[ItemType.LUCKY_CHARM]["cost"]
    await _give_coins(session, 7040, cost * 3)

    # Craft 2 lucky charms
    await craft_item(session, user_id=7040, item_type=ItemType.LUCKY_CHARM)
    await craft_item(session, user_id=7040, item_type=ItemType.LUCKY_CHARM)

    inventory = await get_inventory(session, user_id=7040)
    assert len(inventory) == 1
    entry = inventory[0]
    assert entry["item_type"] == ItemType.LUCKY_CHARM
    assert entry["count"] == 2
