"""
Inline-mode handler.

When a user types @BestBIOwarsrobot in any chat, they see two result cards:
  1. Their personal BioWars player card (stats, status, virus, immunity).
  2. An invite card with a personal referral link.

Requires inline mode to be enabled in BotFather for the bot.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    MessageEntity,
)
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.player import get_player_profile
from bot.services.premium import STATUS_CONFIG, UserStatus, format_username
from bot.utils.chat import dlvl
from bot.utils.emoji import virus_name_entities


def _utf16_len(s: str) -> int:
    """Return the number of UTF-16 code units for string s.

    Telegram entity offsets/lengths count UTF-16 code units, not Python
    characters.  For BMP characters (U+0000–U+FFFF) this equals len(s);
    for supplementary characters (e.g. most emoji) each Python char counts
    as 2 UTF-16 code units.
    """
    return len(s.encode("utf-16-le")) // 2


router = Router(name="inline")

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

_INVITE_MSG = (
    "🧬 <b>BioWars</b> — PvP-игра с био-войнами в Telegram!\n\n"
    "🦠 Качай вирус и заражай соперников\n"
    "🛡 Прокачивай иммунитет и защищайся\n"
    "🏰 Вступай в альянсы и участвуй в ивентах\n\n"
    '👉 <a href="https://t.me/BestBIOwarsrobot?start=ref_{user_id}">Играть со мной!</a>'
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

    has_virus = bool(v)
    has_immunity = bool(im)

    virus_name_raw: str = v.get("name", "Не создан") if has_virus else "Не создан"
    virus_level_raw: int | None = v.get("level") if has_virus else None
    virus_level_display = dlvl(virus_level_raw) if virus_level_raw is not None else None
    immunity_level_raw: int | None = im.get("level") if has_immunity else None
    immunity_level_display = dlvl(immunity_level_raw) if immunity_level_raw is not None else None

    active_infections: int = profile.get("infections_sent_count", 0)

    status_raw: str = u.get("status", "FREE")
    is_premium = status_raw != "FREE"
    status_emoji, status_name = _resolve_status(status_raw)

    display_name = format_username(
        base_username=u.get("username") or str(user_id),
        prefix=u.get("premium_prefix"),
        is_premium_active=is_premium,
        display_name=u.get("display_name"),
        status_emoji=status_emoji,
    )

    bio_coins: int = u.get("bio_coins", 0)

    immunity_str = (
        f"ур. {immunity_level_display}"
        if has_immunity and immunity_level_display is not None
        else "Не создан"
    )

    # Build card as plain text so that we can pass MessageEntity objects for
    # both bold formatting and custom emoji.  Telegram inline results support
    # the ``entities`` parameter of InputTextMessageContent; using it together
    # with parse_mode="HTML" is not allowed, so we express ALL formatting via
    # entities instead.
    header = "🧬 BioWars — Карточка игрока\n\n"
    line_name = f"👤 {display_name}\n"
    # Status line — only shown for premium users
    line_status = f"🏅 Статус: {status_name}\n" if is_premium else ""
    line_virus_prefix = "💊 Вирус: "
    line_virus_suffix = (
        f" (ур. {virus_level_display})\n" if has_virus and virus_level_display is not None else "\n"
    )
    line_immunity = f"🛡 Иммунитет: {immunity_str}\n"
    line_sent = f"☣️ Заражений: {active_infections}\n"
    line_coins = f"🧫 Баланс: {bio_coins:,}\n\n"
    line_bot = "▶️ Играть: t.me/BestBIOwarsrobot"

    # Build card_text carefully: virus name is inserted between prefix and suffix
    # so that we can place MessageEntity offsets correctly.
    virus_name_in_card = virus_name_raw if has_virus else "Не создан"

    card_text = (
        header
        + line_name
        + line_status
        + line_virus_prefix
        + virus_name_in_card
        + line_virus_suffix
        + line_immunity
        + line_sent
        + line_coins
        + line_bot
    )

    # --- Entities ---------------------------------------------------------- #
    # Bold for the header line "BioWars — Карточка игрока"
    bold_start = _utf16_len("🧬 ")
    bold_text = "BioWars — Карточка игрока"
    card_entities: list[MessageEntity] = [
        MessageEntity(type="bold", offset=bold_start, length=_utf16_len(bold_text)),
    ]

    # Custom emoji entities for the virus name (shifted to their position in
    # the full card_text).  The offset depends on whether the status line is
    # present (premium users only).
    virus_offset = _utf16_len(header + line_name + line_status + line_virus_prefix)
    if has_virus:
        card_entities.extend(
            virus_name_entities(
                virus_name_in_card,
                v.get("name_entities_json"),
                offset=virus_offset,
            )
        )

    # Description for the inline result picker
    desc_virus_part = f"💊 {virus_name_raw}" if has_virus else "💊 Не создан"
    desc_immunity_part = f"🛡 Иммунитет {immunity_str}" if has_immunity else "🛡 Не создан"
    result_card = InlineQueryResultArticle(
        id="my_card",
        title="🧬 BioWars — Мой профиль",
        description=f"{desc_virus_part} | {desc_immunity_part} | {bio_coins:,} 🧫",
        input_message_content=InputTextMessageContent(
            message_text=card_text,
            entities=card_entities,
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
