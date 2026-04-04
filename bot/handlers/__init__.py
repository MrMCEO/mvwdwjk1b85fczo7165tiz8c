from bot.handlers.admin import router as admin_router
from bot.handlers.alliance import router as alliance_router
from bot.handlers.attack import router as attack_router
from bot.handlers.events import router as events_router
from bot.handlers.immunity import router as immunity_router
from bot.handlers.info import router as info_router
from bot.handlers.laboratory import router as laboratory_router
from bot.handlers.market import router as market_router
from bot.handlers.menu import router as menu_router
from bot.handlers.mutations import router as mutations_router
from bot.handlers.premium import router as premium_router
from bot.handlers.profile import router as profile_router
from bot.handlers.rating import router as rating_router
from bot.handlers.resources import router as resources_router
from bot.handlers.shop import router as shop_router
from bot.handlers.start import router as start_router
from bot.handlers.text_commands import router as text_commands_router
from bot.handlers.virus import router as virus_router

__all__ = [
    "admin_router",
    "start_router",
    "menu_router",
    "virus_router",
    "immunity_router",
    "resources_router",
    "attack_router",
    "shop_router",
    "premium_router",
    "profile_router",
    "rating_router",
    "info_router",
    "mutations_router",
    "alliance_router",
    "events_router",
    "laboratory_router",
    "market_router",
    "text_commands_router",
]
