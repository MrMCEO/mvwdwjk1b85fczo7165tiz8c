import logging

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.main import main_menu_kb
from bot.services.player import get_or_create_player
from bot.services.referral import register_referral

logger = logging.getLogger(__name__)

router = Router(name="start")

_WELCOME_NEW = (
    "🧬 <b>Добро пожаловать в BioWars!</b>\n\n"
    "Ты зарегистрирован в игре!\n\n"
    "Ты попал в мир биологических войн, где каждый игрок — живой организм.\n\n"
    "⚔️ <b>Атакуй</b> других игроков своим вирусом\n"
    "🛡 <b>Защищайся</b> — прокачивай иммунитет\n"
    "💰 <b>Добывай</b> 🧫 BioCoins — основную валюту\n"
    "🔬 <b>Прокачивай</b> вирус и иммунитет по 3 веткам\n\n"
    "Выбери раздел:"
)

_WELCOME_BACK = (
    "🧬 <b>BioWars — Главное меню</b>\n\n"
    "С возвращением! Выбери раздел:"
)


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession) -> None:
    """Handle /start [ref_<referrer_id>] — create or load player, show main menu."""
    tg_id = message.from_user.id
    username = message.from_user.username or ""

    _, is_new = await get_or_create_player(session, tg_id, username)

    # Handle referral deep link: /start ref_<referrer_id>
    args = message.text.split(maxsplit=1)[1] if message.text and " " in message.text else ""
    if args.startswith("ref_"):
        try:
            referrer_id = int(args[4:])
            saved = await register_referral(session, referrer_id, tg_id)
            if saved:
                logger.info(
                    "start: registered referral referrer=%d referred=%d",
                    referrer_id, tg_id,
                )
        except ValueError:
            logger.debug("start: invalid ref argument %r", args)

    name = message.from_user.full_name
    greeting = f"👋 <b>{name}</b>\n\n"
    text = _WELCOME_NEW if is_new else _WELCOME_BACK

    await message.answer(
        greeting + text,
        reply_markup=main_menu_kb(),
        parse_mode="HTML",
    )
