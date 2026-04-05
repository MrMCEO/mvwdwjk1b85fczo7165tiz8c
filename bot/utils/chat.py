from aiogram.types import Message


async def smart_reply(message: Message, text: str, reply_markup=None, parse_mode="HTML", **kwargs):
    """В группах — reply, в ЛС — answer."""
    if message.chat.type in ("group", "supergroup"):
        return await message.reply(text, reply_markup=reply_markup, parse_mode=parse_mode, **kwargs)
    return await message.answer(text, reply_markup=reply_markup, parse_mode=parse_mode, **kwargs)
