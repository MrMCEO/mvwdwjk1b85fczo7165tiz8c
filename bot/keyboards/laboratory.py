"""Laboratory keyboards — lab menu, craft list, inventory."""

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.models.item import ITEM_CONFIG, ItemType


def lab_menu_kb() -> InlineKeyboardMarkup:
    """Main laboratory menu."""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔬 Крафт",      callback_data="lab_craft")
    builder.button(text="📦 Инвентарь",  callback_data="lab_inventory")
    builder.button(text="◀️ Назад",      callback_data="main_menu")
    builder.adjust(2, 1)
    return builder.as_markup()


def lab_craft_kb() -> InlineKeyboardMarkup:
    """List all craftable items with their costs."""
    builder = InlineKeyboardBuilder()
    for item_type in ItemType:
        cfg = ITEM_CONFIG[item_type]
        label = f"{cfg['emoji']} {cfg['name']} — {cfg['cost']} 🧫"
        builder.button(text=label, callback_data=f"lab_craft_{item_type.value}")
    builder.button(text="◀️ Назад", callback_data="lab_menu")
    # 1 per row so names are readable, back button on its own row
    builder.adjust(*([1] * len(ItemType)), 1)
    return builder.as_markup()


def lab_inventory_kb(items: list[dict]) -> InlineKeyboardMarkup:
    """
    Inventory keyboard.

    Each *item* dict (from get_inventory):
      {item_type, name, emoji, desc, count, item_ids: list[int]}

    Shows a "Использовать" button per item type (uses first item_id in the group).
    """
    builder = InlineKeyboardBuilder()
    for item in items:
        first_id = item["item_ids"][0]
        count_suffix = f" x{item['count']}" if item["count"] > 1 else ""
        label = f"{item['emoji']} {item['name']}{count_suffix} — Использовать"
        builder.button(text=label, callback_data=f"lab_use_{first_id}")
    builder.button(text="◀️ Назад", callback_data="lab_menu")
    builder.adjust(*([1] * len(items)), 1)
    return builder.as_markup()
