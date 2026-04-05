from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, InaccessibleMessage


class CallbackOwnerMiddleware(BaseMiddleware):
    """В групповых чатах проверяет, что callback нажал владелец сообщения.

    Логика:
    - В личных сообщениях (private) — пропускает без проверки.
    - В группах/супергруппах — проверяет, что пользователь, нажавший кнопку,
      совпадает с пользователем, которому бот ответил через reply_to_message.
    - Если message недоступен (InaccessibleMessage) — пропускает, чтобы не
      блокировать обработку старых или удалённых сообщений.
    """

    async def __call__(
        self,
        handler: Callable[[CallbackQuery, dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        # Если message недоступен (InaccessibleMessage или None) — пропускаем
        if event.message is None or isinstance(event.message, InaccessibleMessage):
            return await handler(event, data)

        # В личных сообщениях проверка не нужна
        if event.message.chat.type == "private":
            return await handler(event, data)

        # В группе — проверяем reply_to_message
        reply_msg = event.message.reply_to_message
        if reply_msg and reply_msg.from_user:
            if event.from_user.id != reply_msg.from_user.id:
                await event.answer("Это не ваша кнопка!", show_alert=True)
                return None

        return await handler(event, data)
