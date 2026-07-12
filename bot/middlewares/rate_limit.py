import time
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot.i18n import t

WINDOW_SECONDS = 10
MAX_REQUESTS = 10

# Cap on idle users kept in memory; pruned past this threshold to avoid a slow leak.
MAX_TRACKED_USERS = 5000


class RateLimitMiddleware(BaseMiddleware):
    """In-memory anti-abuse: max MAX_REQUESTS per WINDOW_SECONDS per user. Registered on both
    dp.message and dp.callback_query so inline-button clicks share the same counter as messages."""

    def __init__(self) -> None:
        self._hits: dict[int, deque] = defaultdict(deque)

    def _prune_stale_users(self, now: float) -> None:
        stale = [uid for uid, hits in self._hits.items() if not hits or now - hits[-1] > WINDOW_SECONDS]
        for uid in stale:
            del self._hits[uid]

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, (Message, CallbackQuery)) and event.from_user:
            uid = event.from_user.id
            now = time.monotonic()

            if uid not in self._hits and len(self._hits) >= MAX_TRACKED_USERS:
                self._prune_stale_users(now)

            hits = self._hits[uid]
            while hits and now - hits[0] > WINDOW_SECONDS:
                hits.popleft()

            if len(hits) >= MAX_REQUESTS:
                message = t("rate_limited")
                if isinstance(event, CallbackQuery):
                    await event.answer(message, show_alert=True)
                else:
                    await event.answer(message)
                return None

            hits.append(now)

        return await handler(event, data)
