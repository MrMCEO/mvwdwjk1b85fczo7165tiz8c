"""Keyboards package — re-export all keyboard builders."""

from bot.keyboards.attack import attack_confirm_kb, attack_menu_kb, infections_list_kb
from bot.keyboards.common import back_button, confirm_cancel_kb
from bot.keyboards.immunity import immunity_menu_kb, immunity_upgrade_kb
from bot.keyboards.main import main_menu_kb
from bot.keyboards.profile import log_pagination_kb, profile_kb
from bot.keyboards.rating import rating_menu_kb, rating_type_kb
from bot.keyboards.resources import resources_menu_kb
from bot.keyboards.shop import shop_menu_kb
from bot.keyboards.virus import virus_menu_kb, virus_upgrade_kb

__all__ = [
    "main_menu_kb",
    "virus_menu_kb",
    "virus_upgrade_kb",
    "immunity_menu_kb",
    "immunity_upgrade_kb",
    "resources_menu_kb",
    "attack_menu_kb",
    "attack_confirm_kb",
    "infections_list_kb",
    "shop_menu_kb",
    "profile_kb",
    "log_pagination_kb",
    "rating_menu_kb",
    "rating_type_kb",
    "back_button",
    "confirm_cancel_kb",
]
