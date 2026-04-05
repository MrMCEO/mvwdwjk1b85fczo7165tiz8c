import logging

from aiogram import Router
from aiogram.enums import ButtonStyle
from aiogram.filters import CommandStart
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.main import main_menu_kb
from bot.services.player import get_or_create_player, get_player_profile
from bot.services.referral import register_referral
from bot.utils.chat import smart_reply
from bot.utils.stickers import get_sticker

logger = logging.getLogger(__name__)

router = Router(name="start")

# ---------------------------------------------------------------------------
# Welcome texts
# ---------------------------------------------------------------------------

_WELCOME_NEW = (
    "🧬 <b>BioWars</b>\n\n"
    "Добро пожаловать в мир био-войн!\n\n"
    "Здесь каждый создаёт свой вирус, прокачивает\n"
    "его и сражается с другими игроками.\n\n"
    "<b>Что тебя ждёт:</b>\n"
    "🦠 Создай уникальный вирус и дай ему имя\n"
    "⚔️ Заражай других игроков и забирай ресурсы\n"
    "🛡 Строй неприступную иммунную защиту\n"
    "🏰 Вступай в альянс и воюй кланом\n"
    "🧪 Крафти предметы в лаборатории\n"
    "📈 Торгуй на БиоБирже\n\n"
    "<i>Нажми «Начать играть» чтобы создать персонажа!</i>\n"
    "<i>Для подробной информации введи</i> <code>инфо</code>"
)

_WELCOME_BACK_TPL = (
    "🧬 <b>С возвращением!</b>\n\n"
    "Пока тебя не было, мир BioWars не стоял на месте...\n\n"
    "💰 Баланс: <b>{bio_coins:,}</b> 🧫\n"
    "⚔️ Заражений: <b>{infections_count}</b>"
)

# ---------------------------------------------------------------------------
# Guide text (shown by "Как играть?" button)
# ---------------------------------------------------------------------------

_GUIDE_TEXT = (
    "📖 <b>Как играть в BioWars?</b>\n\n"
    "<b>1. Вирус</b>\n"
    "Твоё оружие атаки. Прокачивай летальность, заразность "
    "и скрытность — три ветки развития.\n\n"
    "<b>2. Иммунитет</b>\n"
    "Твоя защита. Развивай барьер, детектирование и регенерацию.\n\n"
    "<b>3. Атака</b>\n"
    "Заражай других игроков — они начинают приносить тебе 🧫 BioCoins "
    "пока не вылечатся.\n\n"
    "<b>4. Ресурсы</b>\n"
    "Добывай 🧫 на базе, торгуй на БиоБирже, получай от заражённых.\n\n"
    "<b>5. Альянс</b>\n"
    "Объединяйся с другими игроками, воюй кланами, захватывай территории.\n\n"
    "<b>6. Рейтинг</b>\n"
    "Борись за место в топе по заражениям, силе вируса и монетам.\n\n"
    "<i>Удачи в мире BioWars!</i> 🧬"
)

# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------

_CHANNEL_URL = "https://t.me/biowars_news"
_INVITE_GROUP_URL = "https://t.me/BestBIOwarsrobot?startgroup=true"


def _welcome_new_kb() -> InlineKeyboardMarkup:
    """Keyboard for the new-player welcome screen."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎮 Начать играть",
                    callback_data="start_play",
                    style=ButtonStyle.SUCCESS,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📖 Как играть?",
                    callback_data="info_guide",
                    style=ButtonStyle.PRIMARY,
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👥 Играть вместе с друзьями!",
                    url=_INVITE_GROUP_URL,
                    style=ButtonStyle.SUCCESS,
                ),
            ],
            [
                InlineKeyboardButton(text="📢 Канал", url=_CHANNEL_URL, style=ButtonStyle.PRIMARY),
                InlineKeyboardButton(text="🎁 Бонус", callback_data="channel_bonus", style=ButtonStyle.SUCCESS),
            ],
        ]
    )


def _guide_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔙 Назад",
                    callback_data="start_play",
                ),
            ]
        ]
    )


# ---------------------------------------------------------------------------
# /start handler
# ---------------------------------------------------------------------------


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession) -> None:
    """Handle /start [ref_<referrer_id>] — create or load player, show welcome screen."""
    tg_id = message.from_user.id
    username = message.from_user.username or ""

    user, is_new = await get_or_create_player(session, tg_id, username)

    # Handle referral deep link: /start ref_<referrer_id>
    args = message.text.split(maxsplit=1)[1] if message.text and " " in message.text else ""
    if args.startswith("ref_"):
        try:
            referrer_id = int(args[4:])
            saved = await register_referral(session, referrer_id, tg_id)
            if saved:
                logger.info(
                    "start: registered referral referrer=%d referred=%d",
                    referrer_id,
                    tg_id,
                )
        except ValueError:
            logger.debug("start: invalid ref argument %r", args)

    if is_new:
        sticker_id = get_sticker("greeting")
        if sticker_id:
            await message.answer_sticker(sticker_id)

        await smart_reply(
            message,
            _WELCOME_NEW,
            reply_markup=_welcome_new_kb(),
        )
    else:
        sticker_id = get_sticker("success")
        if sticker_id:
            await message.answer_sticker(sticker_id)

        profile = await get_player_profile(session, tg_id)
        u = profile.get("user", {})
        bio_coins: int = u.get("bio_coins", 0)
        infections_count: int = profile.get("infections_sent_count", 0)

        text = _WELCOME_BACK_TPL.format(
            bio_coins=bio_coins,
            infections_count=infections_count,
        )
        await smart_reply(
            message,
            text,
            reply_markup=main_menu_kb(),
        )


# ---------------------------------------------------------------------------
# Inline callbacks from the welcome screen
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: c.data == "start_play")
async def cb_start_play(callback: CallbackQuery, session: AsyncSession) -> None:
    """Show the main menu after the player clicks 'Начать играть'."""
    tg_id = callback.from_user.id
    profile = await get_player_profile(session, tg_id)
    u = profile.get("user", {})

    bio_coins: int = u.get("bio_coins", 0)
    premium_coins: int = u.get("premium_coins", 0)
    raw_display = u.get("display_name") or callback.from_user.full_name or "Игрок"
    status: str = u.get("status", "FREE")

    from bot.services.premium import STATUS_CONFIG, UserStatus  # noqa: PLC0415

    try:
        status_cfg = STATUS_CONFIG[UserStatus(status)]
    except (KeyError, ValueError):
        status_cfg = STATUS_CONFIG[UserStatus.FREE]

    status_emoji: str = status_cfg.get("emoji", "")
    status_name: str = status_cfg.get("name", "Бесплатный")

    display_name = raw_display[:32]  # guard against very long names

    header = (
        "🧬 <b>Главное меню</b>\n\n"
        f"👤 {display_name}"
    )
    if status_emoji:
        header += f" │ {status_emoji} {status_name}"
    header += (
        f"\n💰 <b>{bio_coins:,}</b> 🧫"
        f" │ 💎 <b>{premium_coins}</b>"
    )

    await callback.message.edit_text(header, reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(lambda c: c.data == "info_guide")
async def cb_info_guide(callback: CallbackQuery) -> None:
    """Show the game guide."""
    await callback.message.edit_text(_GUIDE_TEXT, reply_markup=_guide_back_kb())
    await callback.answer()


@router.callback_query(lambda c: c.data == "channel_bonus")
async def cb_channel_bonus(callback: CallbackQuery) -> None:
    """Placeholder: subscription check for bonus."""
    await callback.answer(
        "🎁 Подпишись на канал для бонуса!",
        show_alert=True,
    )
