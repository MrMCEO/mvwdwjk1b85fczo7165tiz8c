"""Main menu keyboard."""

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb() -> InlineKeyboardMarkup:
    """Root navigation keyboard with all game sections."""
    builder = InlineKeyboardBuilder()

    # Row 1 — profile (full width)
    builder.button(text="📊 Мой профиль",        callback_data="profile",        style=ButtonStyle.PRIMARY)

    # Row 2 — virus & immunity
    builder.button(text="🦠 Вирус",              callback_data="virus_menu",     style=ButtonStyle.DANGER)
    builder.button(text="🛡 Иммунитет",          callback_data="immunity_menu",  style=ButtonStyle.SUCCESS)

    # Row 3 — attack & resources
    builder.button(text="⚔️ Атака",              callback_data="attack_menu",    style=ButtonStyle.DANGER)
    builder.button(text="💰 Ресурсы",            callback_data="resources_menu", style=ButtonStyle.SUCCESS)

    # Row 4 — alliance & laboratory
    builder.button(text="🏰 Альянс",             callback_data="alliance_menu",  style=ButtonStyle.PRIMARY)
    builder.button(text="🔬 Лаборатория",        callback_data="lab_menu",       style=ButtonStyle.PRIMARY)

    # Row 5 — market & rating
    builder.button(text="📈 Биржа",              callback_data="market_menu",    style=ButtonStyle.PRIMARY)
    builder.button(text="🏆 Рейтинг",            callback_data="rating_menu",    style=ButtonStyle.PRIMARY)

    # Row 6 — shop & events
    builder.button(text="💎 Магазин",            callback_data="shop_menu",      style=ButtonStyle.SUCCESS)
    builder.button(text="🌍 Ивенты",             callback_data="events_menu",    style=ButtonStyle.PRIMARY)

    # Row 7 — premium & referrals
    builder.button(text="⭐ Премиум",            callback_data="premium_menu",   style=ButtonStyle.SUCCESS)
    builder.button(text="🤝 Рефералы",           callback_data="referral_menu",  style=ButtonStyle.PRIMARY)

    # Row 8 — mutations & transfer
    builder.button(text="🧬 Мутации",            callback_data="mutations_menu", style=ButtonStyle.PRIMARY)
    builder.button(text="💸 Передать",           callback_data="transfer_menu",  style=ButtonStyle.SUCCESS)

    # Row 9 — settings (full width)
    builder.button(text="⚙️ Настройки",          callback_data="settings_menu",  style=ButtonStyle.PRIMARY)

    # Layout: 1, 2, 2, 2, 2, 2, 2, 2, 1
    builder.adjust(1, 2, 2, 2, 2, 2, 2, 2, 1)
    return builder.as_markup()
