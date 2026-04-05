from aiogram import Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from bot.utils.chat import smart_reply

router = Router(name="info")

GUIDE_URL = "https://telegra.ph/BioWars--Polnyj-gajd-po-igre-04-05"

INFO_TEXT = (
    "🧬 <b>BioWars — Справка</b>\n"
    "━━━━━━━━━━━━━━━━━━━━\n\n"
    "⚔️ <b>Основные разделы</b>\n"
    "<code>/start</code> — главное меню\n"
    "<code>/info</code> — эта справка\n"
    "<code>/promo КОД</code> — активировать промокод\n\n"
    "🦠 <b>Игровые механики</b>\n"
    "<i>Вирус</i> — прокачивай атаку, заразность и скрытность\n"
    "<i>Иммунитет</i> — развивай защиту по трём веткам\n"
    "<i>Атака</i> — заражай других игроков, получай ресурсы\n"
    "<i>Ресурсы</i> — добывай и трать 🧫 BioCoins\n\n"
    "🏰 <b>Социальные возможности</b>\n"
    "<i>Альянсы</i> — создавай и вступай в кланы\n"
    "<i>Рефералы</i> — приглашай друзей и получай бонусы\n"
    "<i>Рейтинг</i> — соревнуйся с другими игроками\n\n"
    "💎 <b>Дополнительно</b>\n"
    "<i>Лаборатория</i> — крафт предметов за BioCoins\n"
    "<i>Биржа</i> — торговля с другими игроками\n"
    "<i>Магазин</i> — покупка премиум-валюты\n\n"
    "━━━━━━━━━━━━━━━━━━━━\n"
    "📖 <i>Подробные механики, формулы и советы — в гайде:</i>"
)


def _info_kb() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📖 Открыть гайд", url=GUIDE_URL)
    builder.adjust(1)
    return builder.as_markup()


@router.message(Command("info"))
async def cmd_info(message: Message) -> None:
    await smart_reply(
        message,
        INFO_TEXT,
        reply_markup=_info_kb(),
        disable_web_page_preview=True,
    )
