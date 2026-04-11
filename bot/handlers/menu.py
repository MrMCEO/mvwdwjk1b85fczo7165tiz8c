"""Main menu handler — shows root navigation keyboard."""

from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.main import main_menu_kb
from bot.services.player import get_menu_header_data

router = Router(name="menu")


async def _build_main_menu_text(callback: CallbackQuery, session: AsyncSession) -> str:
    """Compose the main menu header with live player stats."""
    tg_id = callback.from_user.id
    u = await get_menu_header_data(session, tg_id)

    bio_coins: int = u.get("bio_coins", 0)
    premium_coins: int = u.get("premium_coins", 0)
    raw_display: str = u.get("display_name") or callback.from_user.full_name or "Игрок"
    status: str = u.get("status", "FREE")

    from bot.services.premium import STATUS_CONFIG, UserStatus  # noqa: PLC0415

    try:
        status_cfg = STATUS_CONFIG[UserStatus(status)]
    except (KeyError, ValueError):
        status_cfg = STATUS_CONFIG[UserStatus.FREE]

    status_emoji: str = status_cfg.get("emoji", "")
    status_name: str = status_cfg.get("name", "Бесплатный")

    display_name = raw_display[:32]

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
    return header


@router.callback_query(lambda c: c.data == "main_menu")
async def show_main_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    """Return to the main menu from any section."""
    text = await _build_main_menu_text(callback, session)
    await callback.message.edit_text(text, reply_markup=main_menu_kb())
    await callback.answer()
