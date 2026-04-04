from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="info")

GUIDE_URL = "https://telegra.ph/BioWars--Polnyj-gajd-po-igre-04-04"


@router.message(Command("info"))
async def cmd_info(message: Message) -> None:
    await message.answer(
        '📖 <b>Полный гайд по BioWars</b>\n\n'
        'Подробное описание всех механик, веток прокачки, '
        'формул и советов для новичков:\n\n'
        f'👉 <a href="{GUIDE_URL}">Открыть гайд</a>',
        parse_mode="HTML",
        disable_web_page_preview=False,
    )
