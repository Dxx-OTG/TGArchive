"""Shared inline-keyboard pagination for the bot's listings (members, groups, channels, searches).

Each listing re-derives its full item list per page and slices it here, so callback_data only needs
to carry a page number (and, for a group's members, the group id) - well under Telegram's 64-byte limit.
"""
import secrets
from collections import OrderedDict
from typing import Sequence, TypeVar

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.i18n import t

PER_PAGE = 50

T = TypeVar("T")

# Shared store for short tokens standing in for data that won't fit in callback_data / a deep-link
# start param (Telegram's 64-byte / restricted-charset limits): search queries, and the in-place
# card deep links (bot/inplace.py) whose JSON payload can't be inlined. Bounded LRU; oldest fall off.
# The cap is high because EVERY clickable name/link in a list mints a token at render time (a full
# page can be ~90), and a token must survive until the user taps it - a small cap evicted still-shown
# links, so taps silently did nothing. At ~160 B/entry this stays a few MB.
_MAX_TOKENS = 50000
_token_store: "OrderedDict[str, str]" = OrderedDict()


def store_token(value: str) -> str:
    token = secrets.token_urlsafe(8)
    _token_store[token] = value
    _token_store.move_to_end(token)
    while len(_token_store) > _MAX_TOKENS:
        _token_store.popitem(last=False)
    return token


def get_token(token: str) -> str | None:
    return _token_store.get(token)


def page_line(page: int, total_pages: int) -> str:
    """The "Page x/y" line, or "" when there's a single page (keeps short results uncluttered)."""
    return t("page_indicator", page=page + 1, total=total_pages) if total_pages > 1 else ""


def paginate(items: Sequence[T], page: int, per_page: int = PER_PAGE) -> tuple[Sequence[T], int, int]:
    """Return (page_items, clamped_page, total_pages). page is clamped into range so a stale button
    can never index out of bounds."""
    total_pages = max(1, (len(items) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    start = page * per_page
    return items[start:start + per_page], page, total_pages


def btn(text: str, data: str) -> InlineKeyboardButton:
    """A single callback button - the one-liner shared by every keyboard builder."""
    return InlineKeyboardButton(text=text, callback_data=data)


def nav_row(prefix: str, page: int, total_pages: int) -> list[InlineKeyboardButton]:
    """Just the Back/Next buttons (callback_data f"{prefix}:{page}"), possibly empty. For keyboards
    that have other rows (e.g. one button per result) above this nav row."""
    row: list[InlineKeyboardButton] = []
    if page > 0:
        row.append(InlineKeyboardButton(text=t("page_prev"), callback_data=f"{prefix}:{page - 1}"))
    if page < total_pages - 1:
        row.append(InlineKeyboardButton(text=t("page_next"), callback_data=f"{prefix}:{page + 1}"))
    return row


async def safe_edit_text(message: Message, text: str, reply_markup: InlineKeyboardMarkup | None) -> None:
    """edit_text that swallows Telegram's "message is not modified" (e.g. a double-tap on the same
    page), which is harmless, while still surfacing any real error."""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            raise


# Telegram invalidates a callback query a short while after it's sent; answering one that already
# expired raises TelegramBadRequest ("query is too old and response timeout expired or query ID is
# invalid"). There's nothing to retry - the tap already happened - so this is always safe to swallow;
# any OTHER TelegramBadRequest (a real bug) still surfaces. Every callback handler in the bot should
# answer through this instead of calling callback.answer() directly, so a handler that ends up doing
# slow work before answering (network calls, a FloodWait sleep, …) can never crash the update.
_EXPIRED_QUERY_MARKERS = ("query is too old", "query id is invalid", "response timeout expired")


async def safe_answer(callback: CallbackQuery, text: str | None = None, show_alert: bool = False) -> None:
    try:
        await callback.answer(text, show_alert=show_alert)
    except TelegramBadRequest as e:
        if not any(marker in str(e).lower() for marker in _EXPIRED_QUERY_MARKERS):
            raise
