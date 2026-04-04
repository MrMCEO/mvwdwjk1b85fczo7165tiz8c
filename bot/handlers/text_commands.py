"""
Text command handlers — русскоязычные команды без префикса /.

Позволяет пользователям писать команды на русском, не переключая раскладку.
Роутер должен подключаться ПОСЛЕДНИМ, чтобы не перехватывать FSM-ввод.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.handlers.immunity import _fmt_immunity_stats
from bot.handlers.info import GUIDE_URL
from bot.handlers.profile import _fmt_profile
from bot.handlers.resources import _fmt_resources
from bot.handlers.virus import _fmt_virus_stats
from bot.keyboards.alliance import alliance_info_kb, alliance_no_clan_kb
from bot.keyboards.attack import attack_menu_kb
from bot.keyboards.immunity import immunity_menu_kb
from bot.keyboards.main import main_menu_kb
from bot.keyboards.profile import profile_kb
from bot.keyboards.rating import rating_menu_kb
from bot.keyboards.resources import resources_menu_kb
from bot.keyboards.shop import shop_menu_kb
from bot.keyboards.virus import virus_menu_kb
from bot.services.alliance import get_alliance_info
from bot.services.donation import EXCHANGE_RATE
from bot.services.player import get_or_create_player, get_player_profile
from bot.services.resource import get_balance
from bot.services.upgrade import get_immunity_stats, get_virus_stats

router = Router(name="text_commands")

# ---------------------------------------------------------------------------
# Наборы триггеров для каждой секции (сравниваем с lower())
# ---------------------------------------------------------------------------

_MENU_TRIGGERS = {"профиль", "старт", "меню", "начать"}

_VIRUS_TRIGGERS = {"вирус", "мой вирус", "🦠 мой вирус"}

_IMMUNITY_TRIGGERS = {"иммунитет", "мой иммунитет", "🛡 мой иммунитет"}

_ATTACK_TRIGGERS = {"атака", "атаковать", "⚔️ атаковать"}

_RESOURCES_TRIGGERS = {"ресурсы", "💰 ресурсы"}

_RATING_TRIGGERS = {"рейтинг", "топ", "🏆 рейтинг"}

_SHOP_TRIGGERS = {"магазин", "шоп", "донат", "💎 магазин"}

_INFO_TRIGGERS = {"инфо", "помощь", "гайд", "как играть"}

_PROFILE_TRIGGERS = {"мой профиль", "📊 мой профиль"}

_ALLIANCE_TRIGGERS = {"альянс", "клан", "🏰 альянс"}


# ---------------------------------------------------------------------------
# Главное меню
# ---------------------------------------------------------------------------


@router.message(F.text.lower().in_(_MENU_TRIGGERS))
async def text_menu(message: Message, session: AsyncSession) -> None:
    """Текстовая команда: показать главное меню."""
    await get_or_create_player(session, message.from_user.id, message.from_user.username or "")
    await message.answer(
        "🧬 <b>BioWars — Главное меню</b>\n\nВыбери раздел:",
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Мой профиль
# ---------------------------------------------------------------------------


@router.message(F.text.lower().in_(_PROFILE_TRIGGERS))
async def text_profile(message: Message, session: AsyncSession) -> None:
    """Текстовая команда: показать профиль игрока."""
    data = await get_player_profile(session, message.from_user.id)
    text = _fmt_profile(data)
    await message.answer(text, reply_markup=profile_kb(), parse_mode="HTML")


# ---------------------------------------------------------------------------
# Вирус
# ---------------------------------------------------------------------------


@router.message(F.text.lower().in_(_VIRUS_TRIGGERS))
async def text_virus(message: Message, session: AsyncSession) -> None:
    """Текстовая команда: показать меню вируса."""
    data = await get_virus_stats(session, message.from_user.id)
    text = _fmt_virus_stats(data)
    upgrades = data.get("upgrades")
    await message.answer(text, reply_markup=virus_menu_kb(upgrades), parse_mode="HTML")


# ---------------------------------------------------------------------------
# Иммунитет
# ---------------------------------------------------------------------------


@router.message(F.text.lower().in_(_IMMUNITY_TRIGGERS))
async def text_immunity(message: Message, session: AsyncSession) -> None:
    """Текстовая команда: показать меню иммунитета."""
    data = await get_immunity_stats(session, message.from_user.id)
    text = _fmt_immunity_stats(data)
    upgrades = data.get("upgrades")
    await message.answer(text, reply_markup=immunity_menu_kb(upgrades), parse_mode="HTML")


# ---------------------------------------------------------------------------
# Атака
# ---------------------------------------------------------------------------


@router.message(F.text.lower().in_(_ATTACK_TRIGGERS))
async def text_attack(message: Message) -> None:
    """Текстовая команда: показать меню атаки."""
    await message.answer(
        "⚔️ <b>Атака</b>\n\n"
        "Заражай других игроков своим вирусом!\n"
        "Каждая атака имеет кулдаун 30 минут.",
        reply_markup=attack_menu_kb(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Ресурсы
# ---------------------------------------------------------------------------


@router.message(F.text.lower().in_(_RESOURCES_TRIGGERS))
async def text_resources(message: Message, session: AsyncSession) -> None:
    """Текстовая команда: показать меню ресурсов."""
    balance = await get_balance(session, message.from_user.id)
    text = _fmt_resources(balance) if balance else "❌ Игрок не найден."
    await message.answer(text, reply_markup=resources_menu_kb(), parse_mode="HTML")


# ---------------------------------------------------------------------------
# Рейтинг
# ---------------------------------------------------------------------------


@router.message(F.text.lower().in_(_RATING_TRIGGERS))
async def text_rating(message: Message) -> None:
    """Текстовая команда: показать меню рейтинга."""
    await message.answer(
        "🏆 <b>Рейтинги</b>\n\nВыбери тип рейтинга:",
        reply_markup=rating_menu_kb(),
        parse_mode="HTML",
    )


# ---------------------------------------------------------------------------
# Магазин
# ---------------------------------------------------------------------------


@router.message(F.text.lower().in_(_SHOP_TRIGGERS))
async def text_shop(message: Message, session: AsyncSession) -> None:
    """Текстовая команда: показать меню магазина."""
    balance = await get_balance(session, message.from_user.id)
    bio = balance.get("bio_coins", 0) if balance else 0
    premium = balance.get("premium_coins", 0) if balance else 0

    text = (
        "💎 <b>Магазин</b>\n\n"
        f"Твой баланс:\n"
        f"🧫 Bio coins: <b>{bio:,}</b>\n"
        f"💎 Premium coins: <b>{premium:,}</b>\n\n"
        f"Курс обмена: 1 premium = {EXCHANGE_RATE} bio_coins\n\n"
        "Покупка premium coins — <i>интеграция платежей в разработке</i> 🚧"
    )
    await message.answer(text, reply_markup=shop_menu_kb(), parse_mode="HTML")


# ---------------------------------------------------------------------------
# Инфо / гайд
# ---------------------------------------------------------------------------


@router.message(F.text.lower().in_(_INFO_TRIGGERS))
async def text_info(message: Message) -> None:
    """Текстовая команда: отправить ссылку на гайд."""
    await message.answer(
        "📖 <b>Полный гайд по BioWars</b>\n\n"
        "Подробное описание всех механик, веток прокачки, "
        "формул и советов для новичков:\n\n"
        f'👉 <a href="{GUIDE_URL}">Открыть гайд</a>',
        parse_mode="HTML",
        disable_web_page_preview=False,
    )


# ---------------------------------------------------------------------------
# Альянс
# ---------------------------------------------------------------------------


@router.message(F.text.lower().in_(_ALLIANCE_TRIGGERS))
async def text_alliance(message: Message, session: AsyncSession) -> None:
    """Текстовая команда: показать меню альянса."""
    info = await get_alliance_info(session, message.from_user.id)
    if info is None:
        await message.answer(
            "🏰 <b>Альянсы</b>\n\n"
            "Ты не состоишь ни в каком альянсе.\n\n"
            "Создай свой или вступи в существующий!",
            reply_markup=alliance_no_clan_kb(),
            parse_mode="HTML",
        )
    else:
        from bot.handlers.alliance import _fmt_alliance_info
        text = _fmt_alliance_info(info)
        await message.answer(
            text,
            reply_markup=alliance_info_kb(info["user_role"]),
            parse_mode="HTML",
        )
