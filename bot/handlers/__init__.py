from bot.handlers.attack import router as attack_router
from bot.handlers.immunity import router as immunity_router
from bot.handlers.menu import router as menu_router
from bot.handlers.profile import router as profile_router
from bot.handlers.rating import router as rating_router
from bot.handlers.resources import router as resources_router
from bot.handlers.shop import router as shop_router
from bot.handlers.start import router as start_router
from bot.handlers.virus import router as virus_router

__all__ = [
    "start_router",
    "menu_router",
    "virus_router",
    "immunity_router",
    "resources_router",
    "attack_router",
    "shop_router",
    "profile_router",
    "rating_router",
]
