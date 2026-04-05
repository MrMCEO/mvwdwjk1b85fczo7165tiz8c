"""
Moderation handlers for group chats.

Commands (groups/supergroups only):
  /ban [user_id] <reason> <duration>  — ban a user (reply or user_id)
  /mute [user_id] <reason> <duration> — mute a user (reply or user_id)
  /unban @username|user_id            — unban a user (reply or user_id)
  /unmute @username|user_id           — unmute a user (reply or user_id)

Duration formats: 1min, 5min, 30min, 1h, 2h, 12h, 1d, 7d, 30d, 999d, forever
Default on ban: forever; default on mute: 1h.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta
from html import escape

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import (
    CallbackQuery,
    ChatMemberAdministrator,
    ChatMemberOwner,
    ChatPermissions,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.reports import should_notify_report, toggle_report_notify
from bot.utils.chat import smart_reply
from bot.utils.throttle import check_throttle

logger = logging.getLogger(__name__)

router = Router(name="moderation")

# Cache for bot.me() to avoid repeated API calls
_bot_me_id: int | None = None


async def _get_bot_me_id(bot: Bot) -> int:
    """Return bot's own user_id, fetching and caching it once per process."""
    global _bot_me_id
    if _bot_me_id is None:
        me = await bot.me()
        _bot_me_id = me.id
    return _bot_me_id

# Only handle in groups / supergroups
router.message.filter(F.chat.type.in_({"group", "supergroup"}))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(
    r"^(\d+)\s*(min|mins|minutes|h|hours|d|days)$",
    re.IGNORECASE,
)


def _parse_duration(s: str) -> timedelta | None:
    """Parse a human-readable duration string into a timedelta.

    Supported formats:
        Nmin / Nmins / Nminutes — minutes
        Nh / Nhours             — hours
        Nd / Ndays              — days
        forever / 999d          — returns None (permanent)

    Returns None for permanent / unrecognised input.
    """
    s = s.strip().lower()
    if s in ("forever", "perm", "permanent"):
        return None

    m = _DURATION_RE.match(s)
    if not m:
        return None

    value = int(m.group(1))
    unit = m.group(2).lower()

    if unit in ("min", "mins", "minutes"):
        td = timedelta(minutes=value)
    elif unit in ("h", "hours"):
        td = timedelta(hours=value)
    else:  # d, days
        if value >= 999:
            return None  # treat as permanent
        td = timedelta(days=value)

    return td


def _format_duration(td: timedelta | None) -> str:
    """Return a human-readable representation of a timedelta."""
    if td is None:
        return "навсегда"

    total_seconds = int(td.total_seconds())
    if total_seconds < 3600:
        mins = total_seconds // 60
        return f"{mins} мин"
    if total_seconds < 86400:
        hours = total_seconds // 3600
        return f"{hours} ч"
    days = total_seconds // 86400
    return f"{days} д"


async def _is_chat_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Return True if *user_id* is an administrator or creator of *chat_id*."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return isinstance(member, (ChatMemberAdministrator, ChatMemberOwner))
    except TelegramAPIError:
        return False


async def _resolve_target(
    message: Message,
    args: list[str],
) -> tuple[int | None, list[str]]:
    """Determine the target user_id and remaining argument tokens.

    Priority:
    1. Reply-to message — user_id from replied message, args unchanged.
    2. First arg is a numeric user_id — consumed from args.

    Returns (user_id | None, remaining_args).
    """
    # Reply takes precedence
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user.id, args

    # First arg as numeric user_id
    if args and args[0].lstrip("@").isdigit():
        return int(args[0].lstrip("@")), args[1:]

    return None, args


def _parse_args(raw: str) -> tuple[str, timedelta | None, bool]:
    """Split raw command arguments into (reason, duration, duration_is_default).

    Scans tokens right-to-left for a duration token; everything else is the reason.
    Returns duration_is_default=True when no duration was found in args.
    """
    tokens = raw.strip().split()
    duration: timedelta | None = None
    duration_is_default = True

    if tokens:
        last = tokens[-1]
        parsed = _parse_duration(last)
        _last_lower = last.lower()
        _is_duration_token = (
            parsed is not None
            or _last_lower in ("forever", "perm", "permanent")
            or bool(re.match(r"^\d+\s*(min|mins|minutes|h|hours|d|days)$", last, re.IGNORECASE))
        )
        if _is_duration_token:
            # last token is a duration (even None means "forever" explicitly)
            duration = parsed
            duration_is_default = False
            tokens = tokens[:-1]

    reason = " ".join(tokens).strip() or "не указана"
    return reason, duration, duration_is_default


# ---------------------------------------------------------------------------
# /ban
# ---------------------------------------------------------------------------


@router.message(Command("ban"))
async def cmd_ban(message: Message, bot: Bot) -> None:
    """Ban a user from the group."""
    caller_id = message.from_user.id  # type: ignore[union-attr]
    chat_id = message.chat.id

    # Check caller is admin
    if not await _is_chat_admin(bot, chat_id, caller_id):
        await smart_reply(message, "У вас нет прав для использования этой команды.")
        return

    # Check bot is admin
    bot_me_id = await _get_bot_me_id(bot)
    if not await _is_chat_admin(bot, chat_id, bot_me_id):
        await smart_reply(message, "Я не админ в этом чате — выдайте мне права администратора.")
        return

    raw_args = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else ""  # type: ignore[union-attr]
    args = raw_args.split()

    target_id, remaining_args = await _resolve_target(message, args)
    if target_id is None:
        await smart_reply(
            message,
            "Укажите пользователя: ответьте на его сообщение или передайте user_id.",
        )
        return

    reason, duration, _ = _parse_args(" ".join(remaining_args))

    # Guard: cannot ban the bot itself
    if target_id == bot_me_id:
        await smart_reply(message, "Нельзя забанить меня.")
        return

    # Guard: cannot ban other admins
    if await _is_chat_admin(bot, chat_id, target_id):
        await smart_reply(message, "Нельзя забанить администратора.")
        return

    until_date = datetime.now(UTC) + duration if duration else None

    try:
        await bot.ban_chat_member(chat_id, target_id, until_date=until_date)
    except TelegramForbiddenError:
        await smart_reply(message, "Недостаточно прав для бана этого пользователя.")
        return
    except TelegramBadRequest as e:
        await smart_reply(message, f"Ошибка Telegram API: {e.message}")
        return
    except TelegramAPIError as e:
        logger.warning("ban_chat_member failed: %s", e)
        await smart_reply(message, "Не удалось забанить пользователя. Попробуйте позже.")
        return

    duration_str = _format_duration(duration)

    # Try to get a display name for the target
    try:
        member = await bot.get_chat_member(chat_id, target_id)
        name = f"@{member.user.username}" if member.user.username else f"id{target_id}"
    except TelegramAPIError:
        name = f"id{target_id}"

    await smart_reply(
        message,
        f"🚫 {name} забанен на {duration_str}.\nПричина: {escape(reason)}",
    )


# ---------------------------------------------------------------------------
# /mute
# ---------------------------------------------------------------------------


@router.message(Command("mute"))
async def cmd_mute(message: Message, bot: Bot) -> None:
    """Restrict a user from sending messages."""
    caller_id = message.from_user.id  # type: ignore[union-attr]
    chat_id = message.chat.id

    if not await _is_chat_admin(bot, chat_id, caller_id):
        await smart_reply(message, "У вас нет прав для использования этой команды.")
        return

    bot_me_id = await _get_bot_me_id(bot)
    if not await _is_chat_admin(bot, chat_id, bot_me_id):
        await smart_reply(message, "Я не админ в этом чате — выдайте мне права администратора.")
        return

    raw_args = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else ""  # type: ignore[union-attr]
    args = raw_args.split()

    target_id, remaining_args = await _resolve_target(message, args)
    if target_id is None:
        await smart_reply(
            message,
            "Укажите пользователя: ответьте на его сообщение или передайте user_id.",
        )
        return

    reason, duration, duration_is_default = _parse_args(" ".join(remaining_args))

    # Default mute duration: 1 hour
    if duration_is_default:
        duration = timedelta(hours=1)

    if target_id == bot_me_id:
        await smart_reply(message, "Нельзя замутить меня.")
        return

    if await _is_chat_admin(bot, chat_id, target_id):
        await smart_reply(message, "Нельзя замутить администратора.")
        return

    until_date = datetime.now(UTC) + duration if duration else None

    # Remove all send permissions
    no_send = ChatPermissions(
        can_send_messages=False,
        can_send_audios=False,
        can_send_documents=False,
        can_send_photos=False,
        can_send_videos=False,
        can_send_video_notes=False,
        can_send_voice_notes=False,
        can_send_polls=False,
        can_send_other_messages=False,
    )

    try:
        await bot.restrict_chat_member(chat_id, target_id, no_send, until_date=until_date)
    except TelegramForbiddenError:
        await smart_reply(message, "Недостаточно прав для мута этого пользователя.")
        return
    except TelegramBadRequest as e:
        await smart_reply(message, f"Ошибка Telegram API: {e.message}")
        return
    except TelegramAPIError as e:
        logger.warning("restrict_chat_member failed: %s", e)
        await smart_reply(message, "Не удалось замутить пользователя. Попробуйте позже.")
        return

    duration_str = _format_duration(duration)

    try:
        member = await bot.get_chat_member(chat_id, target_id)
        name = f"@{member.user.username}" if member.user.username else f"id{target_id}"
    except TelegramAPIError:
        name = f"id{target_id}"

    await smart_reply(
        message,
        f"🔇 {name} замучен на {duration_str}.\nПричина: {escape(reason)}",
    )


# ---------------------------------------------------------------------------
# /unban
# ---------------------------------------------------------------------------


@router.message(Command("unban"))
async def cmd_unban(message: Message, bot: Bot) -> None:
    """Unban a user from the group."""
    caller_id = message.from_user.id  # type: ignore[union-attr]
    chat_id = message.chat.id

    if not await _is_chat_admin(bot, chat_id, caller_id):
        await smart_reply(message, "У вас нет прав для использования этой команды.")
        return

    bot_me_id = await _get_bot_me_id(bot)
    if not await _is_chat_admin(bot, chat_id, bot_me_id):
        await smart_reply(message, "Я не админ в этом чате — выдайте мне права администратора.")
        return

    raw_args = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else ""  # type: ignore[union-attr]
    args = raw_args.split()

    target_id, _ = await _resolve_target(message, args)
    if target_id is None:
        await smart_reply(
            message,
            "Укажите пользователя: ответьте на его сообщение или передайте user_id.",
        )
        return

    try:
        await bot.unban_chat_member(chat_id, target_id, only_if_banned=True)
    except TelegramForbiddenError:
        await smart_reply(message, "Недостаточно прав для разбана этого пользователя.")
        return
    except TelegramBadRequest as e:
        await smart_reply(message, f"Ошибка Telegram API: {e.message}")
        return
    except TelegramAPIError as e:
        logger.warning("unban_chat_member failed: %s", e)
        await smart_reply(message, "Не удалось разбанить пользователя. Попробуйте позже.")
        return

    try:
        # After unban the user is no longer in the chat; use get_chat to get a name
        user_chat = await bot.get_chat(target_id)
        name = f"@{user_chat.username}" if user_chat.username else f"id{target_id}"
    except TelegramAPIError:
        name = f"id{target_id}"

    await smart_reply(message, f"✅ {name} разбанен.")


# ---------------------------------------------------------------------------
# /unmute
# ---------------------------------------------------------------------------


@router.message(Command("unmute"))
async def cmd_unmute(message: Message, bot: Bot) -> None:
    """Restore default chat permissions for a muted user."""
    caller_id = message.from_user.id  # type: ignore[union-attr]
    chat_id = message.chat.id

    if not await _is_chat_admin(bot, chat_id, caller_id):
        await smart_reply(message, "У вас нет прав для использования этой команды.")
        return

    bot_me_id = await _get_bot_me_id(bot)
    if not await _is_chat_admin(bot, chat_id, bot_me_id):
        await smart_reply(message, "Я не админ в этом чате — выдайте мне права администратора.")
        return

    raw_args = message.text.split(maxsplit=1)[1] if len(message.text.split()) > 1 else ""  # type: ignore[union-attr]
    args = raw_args.split()

    target_id, _ = await _resolve_target(message, args)
    if target_id is None:
        await smart_reply(
            message,
            "Укажите пользователя: ответьте на его сообщение или передайте user_id.",
        )
        return

    # Restore default permissions (None = use chat defaults)
    default_perms = ChatPermissions(
        can_send_messages=True,
        can_send_audios=True,
        can_send_documents=True,
        can_send_photos=True,
        can_send_videos=True,
        can_send_video_notes=True,
        can_send_voice_notes=True,
        can_send_polls=True,
        can_send_other_messages=True,
    )

    try:
        await bot.restrict_chat_member(chat_id, target_id, default_perms)
    except TelegramForbiddenError:
        await smart_reply(message, "Недостаточно прав для снятия мута.")
        return
    except TelegramBadRequest as e:
        await smart_reply(message, f"Ошибка Telegram API: {e.message}")
        return
    except TelegramAPIError as e:
        logger.warning("restrict_chat_member (unmute) failed: %s", e)
        await smart_reply(message, "Не удалось снять мут. Попробуйте позже.")
        return

    try:
        member = await bot.get_chat_member(chat_id, target_id)
        name = f"@{member.user.username}" if member.user.username else f"id{target_id}"
    except TelegramAPIError:
        name = f"id{target_id}"

    await smart_reply(message, f"🔊 {name} размучен.")


# ---------------------------------------------------------------------------
# /report — жалоба на нарушителя
# ---------------------------------------------------------------------------


def _report_notify_kb(chat_id: int) -> InlineKeyboardMarkup:
    """Кнопка отключения/включения уведомлений о репортах в данном чате."""
    builder = InlineKeyboardBuilder()
    builder.button(
        text="🔕 Отключить для этого чата",
        callback_data=f"disable_report_notify:{chat_id}",
    )
    return builder.as_markup()


def _format_mention(user) -> str:  # type: ignore[no-untyped-def]
    """Вернуть @username или HTML-ссылку на пользователя."""
    if user.username:
        return f"@{user.username}"
    name = user.full_name or str(user.id)
    return f'<a href="tg://user?id={user.id}">{name}</a>'


@router.message(Command("report"))
async def cmd_report(message: Message, bot: Bot, session: AsyncSession) -> None:
    """Обработка /report — отправить жалобу администраторам чата."""

    # Throttle: не более 1 репорта в 60 секунд от одного пользователя
    remaining = check_throttle(message.from_user.id, "report", cooldown=60.0)  # type: ignore[union-attr]
    if remaining > 0:
        await smart_reply(
            message,
            f"⏳ Подождите {int(remaining)} сек. перед следующей жалобой.",
        )
        return

    # Нужен реплай на сообщение нарушителя
    if message.reply_to_message is None:
        await smart_reply(
            message,
            "❌ Ответьте на сообщение нарушителя командой <b>/report причина</b>.",
        )
        return

    # Причина обязательна
    args = (message.text or "").partition(" ")[2].strip()
    if not args:
        await smart_reply(
            message,
            "❌ Укажите причину жалобы: <b>/report причина</b>.",
        )
        return

    reporter = message.from_user
    violator = message.reply_to_message.from_user

    if violator is None:
        await smart_reply(message, "❌ Не удалось определить нарушителя.")
        return

    # Нельзя репортить самого себя
    if reporter.id == violator.id:  # type: ignore[union-attr]
        await smart_reply(message, "❌ Нельзя пожаловаться на самого себя.")
        return

    # Нельзя репортить бота
    if violator.is_bot:
        await smart_reply(message, "❌ Нельзя пожаловаться на бота.")
        return

    chat = message.chat
    reason = args[:500]

    # Текст сообщения нарушителя (первые 200 символов)
    violator_text = (
        message.reply_to_message.text or message.reply_to_message.caption or ""
    )
    violator_text_preview = violator_text[:200]
    if len(violator_text) > 200:
        violator_text_preview += "…"

    reporter_mention = _format_mention(reporter)
    violator_mention = _format_mention(violator)

    notify_text = (
        f'🚨 <b>Жалоба в чате "{escape(chat.title or "")}"</b>\n\n'
        f"От: {reporter_mention}\n"
        f"На: {violator_mention}\n"
        f"Причина: {escape(reason)}"
    )
    if violator_text_preview:
        notify_text += f'\n\nСообщение: "<i>{escape(violator_text_preview)}</i>"'

    # Получаем список администраторов чата
    try:
        admins = await bot.get_chat_administrators(chat.id)
    except Exception as exc:
        logger.warning(
            "Не удалось получить список админов чата %s: %s", chat.id, exc
        )
        await smart_reply(message, "✅ Жалоба отправлена администраторам.")
        return

    for admin_member in admins:
        admin_user = admin_member.user
        if admin_user.is_bot:
            continue

        # Проверяем настройку уведомлений
        try:
            notify = await should_notify_report(session, admin_user.id, chat.id)
        except Exception as exc:
            logger.warning(
                "Ошибка проверки настроек репорта для admin %s: %s", admin_user.id, exc
            )
            notify = True

        if not notify:
            continue

        try:
            await bot.send_message(
                admin_user.id,
                notify_text,
                parse_mode="HTML",
                reply_markup=_report_notify_kb(chat.id),
            )
        except Exception:
            # Бот заблокирован или диалог не начат — пропускаем
            pass

    await smart_reply(message, "✅ Жалоба отправлена администраторам.")


# ---------------------------------------------------------------------------
# Callback: отключить/включить уведомления о репортах
# ---------------------------------------------------------------------------


@router.callback_query(F.data.startswith("disable_report_notify:"))
async def cb_disable_report_notify(
    callback: CallbackQuery, session: AsyncSession
) -> None:
    """Переключить уведомления о репортах для конкретного чата."""
    try:
        chat_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Ошибка: неверный идентификатор чата.", show_alert=True)
        return

    admin_id = callback.from_user.id

    try:
        new_state = await toggle_report_notify(session, admin_id, chat_id)
    except Exception as exc:
        logger.error("Ошибка toggle_report_notify: %s", exc)
        await callback.answer("Произошла ошибка. Попробуйте позже.", show_alert=True)
        return

    builder = InlineKeyboardBuilder()
    if new_state:
        await callback.answer("🔔 Уведомления о жалобах включены.")
        builder.button(
            text="🔕 Отключить для этого чата",
            callback_data=f"disable_report_notify:{chat_id}",
        )
    else:
        await callback.answer("🔕 Уведомления о жалобах отключены.")
        builder.button(
            text="🔔 Включить для этого чата",
            callback_data=f"disable_report_notify:{chat_id}",
        )

    try:
        await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
    except Exception:
        pass  # Сообщение могло быть удалено
