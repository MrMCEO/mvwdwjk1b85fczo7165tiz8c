"""Shop section keyboard."""

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

PACKAGES = [
    {"id": "pkg_50",  "amount": 50,  "price_rub": 50,  "bonus": 0.00, "label": "50 💎 — 50₽"},
    {"id": "pkg_150", "amount": 150, "price_rub": 150, "bonus": 0.00, "label": "150 💎 — 150₽"},
    {"id": "pkg_300", "amount": 300, "price_rub": 250, "bonus": 0.20, "label": "300 💎 — 250₽ (+20% бонус)"},
    {"id": "pkg_500", "amount": 500, "price_rub": 400, "bonus": 0.25, "label": "500 💎 — 400₽ (+25% бонус)"},
]


def shop_menu_kb() -> InlineKeyboardMarkup:
    """Shop main menu with package purchase buttons and conversion."""
    builder = InlineKeyboardBuilder()
    # Package pairs — 2 per row, SUCCESS style
    for pkg in PACKAGES:
        builder.button(text=f"💎 {pkg['label']}", callback_data=f"buy_pkg_{pkg['id']}", style=ButtonStyle.SUCCESS)
    # Convert — PRIMARY
    builder.button(text="💱 Конвертировать 💎 → 🧫", callback_data="shop_convert_start", style=ButtonStyle.PRIMARY)
    # Premium — mono
    builder.button(text="⭐ Премиум подписка", callback_data="premium_menu")
    # Back — mono
    builder.button(text="🔙 Главное меню", callback_data="main_menu")
    # 4 packages in pairs (2+2), then convert mono, premium mono, back mono
    builder.adjust(2, 2, 1, 1, 1)
    return builder.as_markup()
