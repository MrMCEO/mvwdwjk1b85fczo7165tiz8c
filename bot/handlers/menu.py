"""Main menu handler — shows root navigation keyboard."""

from aiogram import Router
from aiogram.types import CallbackQuery

from bot.keyboards.main import main_menu_kb

router = Router(name="menu")

MAIN_MENU_TEXT = (
    "🧬 <b>BioWars — Главное меню</b>\n\n"
    "Выбери раздел:"
)


@router.callback_query(lambda c: c.data == "main_menu")
async def show_main_menu(callback: CallbackQuery) -> None:
    """Return to the main menu from any section."""
    await callback.message.edit_text(MAIN_MENU_TEXT, reply_markup=main_menu_kb())
    await callback.answer()
