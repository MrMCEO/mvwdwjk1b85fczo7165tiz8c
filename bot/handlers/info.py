from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.utils.chat import smart_reply

router = Router(name="info")

GUIDE_URL = "https://telegra.ph/BioWars--Polnyj-gajd-po-igre-04-04-4"


@router.message(Command("info"))
async def cmd_info(message: Message) -> None:
    await smart_reply(
        message,
        '📖 <b>Полный гайд по BioWars</b>\n\n'
        'Подробное описание всех механик, веток прокачки, '
        'формул и советов для новичков:\n\n'
        f'👉 <a href="{GUIDE_URL}">Открыть гайд</a>',
        disable_web_page_preview=False,
    )
