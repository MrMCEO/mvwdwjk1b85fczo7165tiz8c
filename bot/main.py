import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode

from bot.config import get_settings
from bot.utils.logger import setup_logging
from bot.handlers.admin import router as admin_router
from bot.handlers.broadcast import router as broadcast_router
from bot.handlers.moderation import router as moderation_router
from bot.handlers.alliance import router as alliance_router
from bot.handlers.attack import router as attack_router
from bot.handlers.events import router as events_router
from bot.handlers.suggest import router as suggest_router
from bot.handlers.immunity import router as immunity_router
from bot.handlers.info import router as info_router
from bot.handlers.inline import router as inline_router
from bot.handlers.laboratory import router as laboratory_router
from bot.handlers.market import router as market_router
from bot.handlers.menu import router as menu_router
from bot.handlers.mutations import router as mutations_router
from bot.handlers.premium import router as premium_router
from bot.handlers.profile import router as profile_router
from bot.handlers.rating import router as rating_router
from bot.handlers.referral import router as referral_router
from bot.handlers.resources import router as resources_router
from bot.handlers.settings import router as settings_router
from bot.handlers.shop import router as shop_router
from bot.handlers.start import router as start_router
from bot.handlers.text_commands import router as text_commands_router
from bot.handlers.transfer import router as transfer_router
from bot.handlers.virus import router as virus_router
from bot.middlewares.callback_owner import CallbackOwnerMiddleware
from bot.middlewares.chat_tracker import ChatTrackerMiddleware
from bot.middlewares.db import DbSessionMiddleware
from bot.models.base import init_db
from bot.services.tick import start_scheduler

logger = logging.getLogger(__name__)


async def on_startup(bot: Bot) -> None:
    logger.info("Initialising database...")
    await init_db()
    logger.info("Database ready.")
    await start_scheduler(bot)
    logger.info("Infection tick scheduler started.")


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("Bot starting up...")

    proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    session = AiohttpSession(proxy=proxy) if proxy else AiohttpSession()
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )

    dp = Dispatcher()

    # Register lifecycle hooks
    dp.startup.register(on_startup)

    # Register middlewares (applied to all update types)
    # CallbackOwnerMiddleware runs first (on callback_query observer) so that
    # foreign-button clicks in groups are rejected before a DB session is opened.
    dp.callback_query.middleware(CallbackOwnerMiddleware())
    dp.update.middleware(DbSessionMiddleware())
    # ChatTracker must be AFTER DbSessionMiddleware so the session is available
    dp.message.middleware(ChatTrackerMiddleware())
    dp.callback_query.middleware(ChatTrackerMiddleware())

    # Connect routers — order matters: start first, then menu, then sections
    dp.include_router(start_router)
    dp.include_router(info_router)
    dp.include_router(menu_router)
    dp.include_router(virus_router)
    dp.include_router(immunity_router)
    dp.include_router(resources_router)
    dp.include_router(attack_router)
    dp.include_router(shop_router)
    dp.include_router(profile_router)
    dp.include_router(rating_router)
    dp.include_router(mutations_router)
    dp.include_router(premium_router)
    dp.include_router(alliance_router)
    dp.include_router(events_router)
    dp.include_router(laboratory_router)
    dp.include_router(market_router)
    dp.include_router(referral_router)
    dp.include_router(settings_router)
    dp.include_router(transfer_router)
    # Admin router before text_commands to handle /admin, FSM states, callbacks
    dp.include_router(admin_router)
    dp.include_router(broadcast_router)
    dp.include_router(suggest_router)
    # Moderation commands (group-only: /ban, /mute, /unban, /unmute, /report)
    dp.include_router(moderation_router)
    # Inline-mode handler — before text_commands to avoid interception
    dp.include_router(inline_router)
    # Text commands MUST be last — otherwise may intercept FSM input (e.g. attack username)
    dp.include_router(text_commands_router)

    logger.info("Starting polling...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
