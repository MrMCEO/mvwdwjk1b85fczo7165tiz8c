"""
Inline-mode handler.

When a user types @BestBIOwarsrobot in any chat, they see two result cards:
  1. Their personal BioWars player card (stats, status, virus, immunity).
  2. An invite card with a personal referral link.

Requires inline mode to be enabled in BotFather for the bot.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.player import get_player_profile
from bot.services.premium import STATUS_CONFIG, UserStatus, format_username
from bot.utils.emoji import render_virus_name

router = Router(name="inline")

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_INVITE_MSG = (
    "🧬 <b>BioWars</b> — PvP-игра с био-войнами в Telegram!\n\n"
    "🦠 Качай вирус и заражай соперников\n"
    "🛡 Прокачивай иммунитет и защищайся\n"
    "🏰 Вступай в альянсы и участвуй в ивентах\n\n"
    "👉 https://t.me/BestBIOwarsrobot?start=ref_{user_id}"
)

_UNREGISTERED_MSG = (
    "🧬 <b>BioWars</b> — PvP-игра с био-войнами!\n\n"
    "Качай вирус, заражай соперников, прокачивай иммунитет!\n"
    "👉 @BestBIOwarsrobot"
)


def _resolve_status(status_raw: str) -> tuple[str, str]:
    """Return (emoji, name) for the given raw status string."""
    try:
        key = UserStatus(status_raw)
    except ValueError:
        key = UserStatus.FREE
    cfg = STATUS_CONFIG[key]
    return cfg["emoji"], cfg["name"]


# --------------------------------------------------------------------------- #
# Handler
# --------------------------------------------------------------------------- #


@router.inline_query()
async def inline_handler(query: InlineQuery, session: AsyncSession) -> None:
    """Return player card + invite card when the bot is invoked via inline mode."""
    user_id = query.from_user.id

    profile = await get_player_profile(session, user_id)

    # ------------------------------------------------------------------ #
    # Unregistered user — just show an invitation
    # ------------------------------------------------------------------ #
    if not profile or "error" in profile:
        result = InlineQueryResultArticle(
            id="not_registered",
            title="🧬 BioWars — Зарегистрируйся!",
            description="Нажми, чтобы отправить приглашение",
            input_message_content=InputTextMessageContent(
                message_text=_UNREGISTERED_MSG,
                parse_mode="HTML",
            ),
        )
        await query.answer([result], cache_time=60, is_personal=True)
        return

    # ------------------------------------------------------------------ #
    # Registered user — build the player card
    # ------------------------------------------------------------------ #
    u = profile["user"]
    v = profile.get("virus") or {}
    im = profile.get("immunity") or {}

    virus_name = render_virus_name(v.get("name", "—"), v.get("name_entities_json"))
    virus_level = v.get("level", 0)
    immunity_level = im.get("level", 0)
    sent = profile.get("infections_sent_count", 0)

    status_raw: str = u.get("status", "FREE")
    status_emoji, status_name = _resolve_status(status_raw)

    display_name = format_username(
        base_username=u.get("username") or str(user_id),
        prefix=u.get("premium_prefix"),
        is_premium_active=status_raw != "FREE",
        display_name=u.get("display_name"),
        status_emoji=status_emoji,
    )

    bio_coins: int = u.get("bio_coins", 0)

    card_text = (
        f"🧬 <b>BioWars — Карточка игрока</b>\n\n"
        f"👤 {display_name}\n"
        f"🏅 Статус: {status_emoji} {status_name}\n"
        f"🦠 Вирус: {virus_name} (ур. {virus_level})\n"
        f"🛡 Иммунитет: ур. {immunity_level}\n"
        f"⚔️ Заражений: {sent} исходящих\n"
        f"💰 {bio_coins:,} 🧫\n\n"
        f"👉 @BestBIOwarsrobot"
    )

    result_card = InlineQueryResultArticle(
        id="my_card",
        title=f"🧬 Моя карточка — Вирус ур. {virus_level}",
        description=(
            f"🦠 {v.get('name', 'Вирус')} | "
            f"🛡 Иммунитет ур. {immunity_level} | "
            f"{bio_coins:,} 🧫"
        ),
        input_message_content=InputTextMessageContent(
            message_text=card_text,
            parse_mode="HTML",
        ),
    )

    result_invite = InlineQueryResultArticle(
        id="invite",
        title="🤝 Пригласить в BioWars",
        description="Отправить приглашение с реферальной ссылкой",
        input_message_content=InputTextMessageContent(
            message_text=_INVITE_MSG.format(user_id=user_id),
            parse_mode="HTML",
        ),
    )

    await query.answer([result_card, result_invite], cache_time=30, is_personal=True)
