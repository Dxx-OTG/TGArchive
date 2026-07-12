from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.config import ADMIN_USER_IDS, ADMIN_USERNAMES
from bot.i18n import t
from bot.log import log


def is_admin(tg_user_id: int, username: str | None = None) -> bool:
    if tg_user_id in ADMIN_USER_IDS:
        return True
    return bool(username) and username.lower() in ADMIN_USERNAMES


class AdminOnlyMiddleware(BaseMiddleware):
    """Private bot: nobody outside ADMIN_USER_IDS may use any command, not even /start. Rejected
    attempts are logged to the console so the operator can read their own tg_user_id and add it."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, (Message, CallbackQuery)) and event.from_user and not is_admin(event.from_user.id, event.from_user.username):
            log(f"⛔ Blocked (not in ADMIN_USER_IDS): tg_user_id={event.from_user.id} username={event.from_user.username}")
            message = t("admin_only")
            if isinstance(event, CallbackQuery):
                await event.answer(message, show_alert=True)
            else:
                await event.answer(message)
            return None

        return await handler(event, data)
