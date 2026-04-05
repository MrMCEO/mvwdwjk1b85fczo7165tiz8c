"""Utilities for rendering virus names that contain Telegram custom emoji."""

from __future__ import annotations

import html
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram.types import MessageEntity


def virus_name_entities(
    name: str,
    entities_json: str | None,
    offset: int = 0,
) -> list[MessageEntity]:
    """Return a list of MessageEntity objects for a virus name.

    This is used when building inline-mode messages with the ``entities``
    parameter of ``InputTextMessageContent``, where ``parse_mode`` is not
    set and all formatting must be expressed via entities.

    Args:
        name: Raw virus name string (as stored in DB).
        entities_json: JSON string with ``[{offset, length, custom_emoji_id}]``
                       or *None* when no custom emoji are present.
        offset: Character offset of the virus name within the full message
                text.  Entities returned will have their ``offset`` shifted
                by this value so they point to the correct position in the
                complete message.

    Returns:
        List of ``MessageEntity`` (may be empty).  Import is deferred to
        avoid a hard dependency on aiogram at module import time.
    """
    # Late import so the module stays importable in unit tests that don't
    # have aiogram installed.
    from aiogram.types import MessageEntity as ME  # noqa: PLC0415

    if not entities_json:
        return []

    raw_entities = json.loads(entities_json)
    if not raw_entities:
        return []

    result: list[ME] = []
    for ent in raw_entities:
        result.append(
            ME(
                type="custom_emoji",
                offset=offset + ent["offset"],
                length=ent["length"],
                custom_emoji_id=str(ent["custom_emoji_id"]),
            )
        )
    return result


def render_virus_name(name: str, entities_json: str | None) -> str:
    """Преобразует имя вируса с entities в HTML с tg-emoji тегами.

    Args:
        name: Имя вируса — RAW (не экранированное) значение из БД.
              Функция сама выполняет html.escape() для безопасного вывода.
        entities_json: JSON-строка с массивом [{offset, length, custom_emoji_id}]
                       или None, если кастомных эмодзи нет.

    Returns:
        HTML-строка, готовая для вставки в parse_mode="HTML" сообщение.
    """
    if not entities_json:
        return html.escape(name)

    entities = json.loads(entities_json)
    if not entities:
        return html.escape(name)

    # Сортировать по offset в обратном порядке, чтобы вставки не сдвигали индексы.
    # Offsets от Telegram — позиции символов в исходном raw-тексте (UTF-16 code units,
    # но для BMP-символов совпадает с len()).
    entities_sorted = sorted(entities, key=lambda e: e["offset"], reverse=True)

    # Работаем со списком символов raw-строки, чтобы корректно применять offset/length.
    chars = list(name)

    for ent in entities_sorted:
        offset = ent["offset"]
        length = ent["length"]
        emoji_id = ent["custom_emoji_id"]

        # Извлекаем fallback-символы и экранируем их
        fallback_raw = "".join(chars[offset : offset + length])
        fallback_safe = html.escape(fallback_raw)

        # Экранируем emoji_id для безопасной вставки в атрибут
        safe_emoji_id = html.escape(str(emoji_id), quote=True)

        tag = f'<tg-emoji emoji-id="{safe_emoji_id}">{fallback_safe}</tg-emoji>'

        # Заменяем диапазон символов одним placeholder'ом (сам тег)
        chars[offset : offset + length] = [tag]

    # Экранируем оставшиеся (не-emoji) части и склеиваем результат
    result_parts = []
    for part in chars:
        if part.startswith("<tg-emoji"):
            # Уже готовый HTML-тег, не экранируем
            result_parts.append(part)
        else:
            result_parts.append(html.escape(part))

    return "".join(result_parts)
