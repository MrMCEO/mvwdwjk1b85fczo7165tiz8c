"""
Laboratory handlers — crafting items and managing inventory.

Callbacks:
  lab_menu        — main laboratory screen
  lab_craft       — list of craftable items
  lab_craft_<T>   — craft specific item type T
  lab_inventory   — detailed inventory view
  lab_use_<id>    — use item by id (may trigger FSM for SPY_DRONE)
"""

from __future__ import annotations

from datetime import UTC, datetime
from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.laboratory import lab_craft_kb, lab_inventory_kb, lab_menu_kb
from bot.models.item import ITEM_CONFIG, Item, ItemType
from bot.services.laboratory import (
    craft_item,
    get_inventory,
    spy_on_player,
    use_item,
)

router = Router(name="laboratory")


class LabStates(StatesGroup):
    waiting_for_spy_target = State()


# ---------------------------------------------------------------------------
# Helper to parse ItemType from string
# ---------------------------------------------------------------------------


def _item_type_from_str(value: str) -> ItemType | None:
    try:
        return ItemType(value)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Lab menu
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "lab_menu")
async def cb_lab_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    inventory = await get_inventory(session, callback.from_user.id)
    total_items = sum(i["count"] for i in inventory)

    text = (
        "🔬 <b>Лаборатория</b>\n\n"
        "Здесь ты можешь крафтить предметы за bio_coins.\n"
        "Предметы одноразовые и хранятся в инвентаре.\n\n"
        f"📦 Предметов в инвентаре: <b>{total_items}</b>"
    )
    await callback.message.edit_text(text, reply_markup=lab_menu_kb(), parse_mode="HTML")
    await callback.answer()


# ---------------------------------------------------------------------------
# Craft list
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "lab_craft")
async def cb_lab_craft(callback: CallbackQuery) -> None:
    lines = ["🔬 <b>Крафт предметов</b>\n"]
    for item_type in ItemType:
        cfg = ITEM_CONFIG[item_type]
        lines.append(
            f"{cfg['emoji']} <b>{cfg['name']}</b> — {cfg['cost']} 🧫\n"
            f"   <i>{cfg['desc']}</i>"
        )
    text = "\n".join(lines)
    await callback.message.edit_text(text, reply_markup=lab_craft_kb(), parse_mode="HTML")
    await callback.answer()


# ---------------------------------------------------------------------------
# Craft specific item
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("lab_craft_"))
async def cb_lab_craft_item(callback: CallbackQuery, session: AsyncSession) -> None:
    raw = callback.data.removeprefix("lab_craft_")
    item_type = _item_type_from_str(raw)
    if item_type is None:
        await callback.answer("Неизвестный предмет.", show_alert=True)
        return

    success, message = await craft_item(session, callback.from_user.id, item_type)

    if success:
        await callback.answer("Предмет создан!", show_alert=False)
    else:
        await callback.answer(
            message.replace("<b>", "").replace("</b>", "").replace("<i>", "").replace("</i>", ""),
            show_alert=True,
        )
        return

    # Обновить экран крафта с результатом
    lines = ["🔬 <b>Крафт предметов</b>\n"]
    for it in ItemType:
        cfg = ITEM_CONFIG[it]
        lines.append(
            f"{cfg['emoji']} <b>{cfg['name']}</b> — {cfg['cost']} 🧫\n"
            f"   <i>{cfg['desc']}</i>"
        )
    lines.append(f"\n{message}")
    await callback.message.edit_text(
        "\n".join(lines), reply_markup=lab_craft_kb(), parse_mode="HTML"
    )


# ---------------------------------------------------------------------------
# Inventory view
# ---------------------------------------------------------------------------


@router.callback_query(F.data == "lab_inventory")
async def cb_lab_inventory(callback: CallbackQuery, session: AsyncSession) -> None:
    inventory = await get_inventory(session, callback.from_user.id)

    if not inventory:
        text = (
            "📦 <b>Инвентарь</b>\n\n"
            "Инвентарь пуст.\n"
            "Перейди в раздел 🔬 Крафт, чтобы создать предметы."
        )
        await callback.message.edit_text(
            text, reply_markup=lab_inventory_kb([]), parse_mode="HTML"
        )
        await callback.answer()
        return

    lines = ["📦 <b>Инвентарь</b>\n"]
    for item in inventory:
        count_txt = f" x{item['count']}" if item["count"] > 1 else ""
        lines.append(
            f"{item['emoji']} <b>{item['name']}</b>{count_txt}\n"
            f"   <i>{item['desc']}</i>"
        )

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=lab_inventory_kb(inventory),
        parse_mode="HTML",
    )
    await callback.answer()


# ---------------------------------------------------------------------------
# Use item
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("lab_use_"))
async def cb_lab_use_item(
    callback: CallbackQuery, session: AsyncSession, state: FSMContext
) -> None:
    raw = callback.data.removeprefix("lab_use_")
    try:
        item_id = int(raw)
    except ValueError:
        await callback.answer("Неверный ID предмета.", show_alert=True)
        return

    success, message, extra = await use_item(session, callback.from_user.id, item_id)

    if not success:
        await callback.answer(
            message.replace("<b>", "").replace("</b>", ""),
            show_alert=True,
        )
        return

    # SPY_DRONE: переходим в FSM — ждём username цели
    if extra.get("type") == "spy":
        await state.set_state(LabStates.waiting_for_spy_target)
        await state.update_data(spy_item_id=extra.get("item_id"))
        await callback.message.edit_text(
            "🔭 <b>Дрон-разведчик</b>\n\n"
            "Введи @username или имя пользователя цели разведки:",
            parse_mode="HTML",
        )
        await callback.answer()
        return

    # Для всех прочих предметов — показываем результат и обновляем инвентарь
    inventory = await get_inventory(session, callback.from_user.id)
    result_text = message + "\n\n📦 <b>Инвентарь обновлён</b>"
    await callback.message.edit_text(
        result_text,
        reply_markup=lab_inventory_kb(inventory),
        parse_mode="HTML",
    )
    await callback.answer("Применено!")


# ---------------------------------------------------------------------------
# SPY_DRONE FSM: receive target username
# ---------------------------------------------------------------------------


@router.message(LabStates.waiting_for_spy_target)
async def fsm_spy_target(
    message: Message, session: AsyncSession, state: FSMContext
) -> None:
    state_data = await state.get_data()
    spy_item_id: int | None = state_data.get("spy_item_id")
    await state.clear()

    raw_username = (message.text or "").strip()
    if not raw_username:
        await message.answer("Имя пользователя не может быть пустым.")
        return

    data = await spy_on_player(session, raw_username)
    if data is None:
        await message.answer(
            f"🔭 Игрок <b>{escape(raw_username)}</b> не найден.",
            parse_mode="HTML",
        )
        return

    # Пометить предмет как использованный
    if spy_item_id:
        await _finalize_spy_item(session, message.from_user.id, spy_item_id)

    virus = data.get("virus", {})
    immunity = data.get("immunity", {})

    # Вирус ветки
    v_upgrades = virus.get("upgrades", {})
    v_branches = "\n".join(
        f"   • {branch}: ур. {info['level']}"
        for branch, info in v_upgrades.items()
    ) or "   нет данных"

    # Иммунитет ветки
    im_upgrades = immunity.get("upgrades", {})
    im_branches = "\n".join(
        f"   • {branch}: ур. {info['level']}"
        for branch, info in im_upgrades.items()
    ) or "   нет данных"

    text = (
        f"🔭 <b>Разведка: @{escape(data['username'])}</b>\n\n"
        f"💰 Bio coins: <b>{data['bio_coins']:,}</b> 🧫\n"
        f"🦠 Заражений: <b>{data['active_infections']}</b> (входящих)\n\n"
        f"🦠 <b>Вирус</b>\n"
        f"   Имя: {escape(virus.get('name', '—'))}\n"
        f"   Уровень: {virus.get('level', '—')}\n"
        f"   Атака: {virus.get('attack_power', '—')}\n"
        f"   Заразность: {virus.get('spread_rate', '—')}\n"
        f"   Ветки прокачки:\n{v_branches}\n\n"
        f"🛡 <b>Иммунитет</b>\n"
        f"   Уровень: {immunity.get('level', '—')}\n"
        f"   Сопротивление: {immunity.get('resistance', '—')}\n"
        f"   Обнаружение: {immunity.get('detection_power', '—')}\n"
        f"   Регенерация: {immunity.get('recovery_speed', '—')}\n"
        f"   Ветки прокачки:\n{im_branches}"
    )

    await message.answer(text, reply_markup=lab_menu_kb(), parse_mode="HTML")


async def _finalize_spy_item(
    session: AsyncSession, user_id: int, item_id: int
) -> None:
    """Mark the SPY_DRONE item as used after the target username is resolved."""
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
    if item is not None:
        item.is_used = True
        item.used_at = datetime.now(UTC).replace(tzinfo=None)
        await session.flush()
