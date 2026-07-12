"""In-place deep links: clickable TEXT that, when tapped, edits the CURRENT message instead of
opening an external chat. Inline text can only hold a URL, so every such link is a
`t.me/<bot>?start=g<token>` deep link whose token carries {action, target, msgid, back}; tapping it
fires /start, and bot/modules/start.py's cmd_start edits the message `msgid` into the requested view
(see _inplace_view). Shared here so both the hub (start.py) and the card drills (card_view.py) build
identical links without a circular import.

The rule the whole UI follows: a name/link in ANY list opens that entity's CARD in place - never the
real external chat. Only the card's own title is a real t.me link.
"""
import json
import re
from html import escape

from bot.botinfo import deep_link
from bot.pagination import store_token

# A trailing "/123" message id (and any ?query / #frag) isn't part of the entity handle to resolve.
_MSGID_TAIL = re.compile(r"/\d+/?$")


def inplace_url(payload: dict) -> str | None:
    """The deep-link URL for `payload`, or None if the bot username isn't known yet (pre-startup)."""
    return deep_link(f"g{store_token(json.dumps(payload))}")


def inplace_link(payload: dict, text_html: str) -> str:
    """Clickable text (already HTML-safe) that opens `payload` in place; plain text if not ready."""
    url = inplace_url(payload)
    return f'<a href="{escape(url)}">{text_html}</a>' if url else text_html


def card_link(handle: str, label: str, msgid: int, back: str) -> str:
    """Clickable name that opens `handle`'s CARD in place (editing `msgid`), Back -> the `back`
    callback. `label` is raw text and is escaped here. This is what list rows use for every entity."""
    return inplace_link({"a": "c", "h": handle, "msgid": msgid, "back": back}, escape(label))


def linker(msgid: int | None, back: str):
    """A `(handle, label) -> card link` function for a list rendered in place, or None when there's no
    message to edit (rows then fall back to plain text - never a direct external link). `back` is the
    callback a spawned card's Back should fire to return to this exact list view."""
    if msgid is None:
        return None
    return lambda handle, label: card_link(handle, label, msgid, back)


def sharers_linker(msgid: int | None, back: str):
    """A `(link_key, n) -> clickable "👤 n"` function that opens, in place, the list of users who
    shared that link. None (plain text) when there's no message to edit. `back` returns to this list."""
    if msgid is None:
        return None
    return lambda key, n: inplace_link({"a": "sh", "lk": key, "msgid": msgid, "back": back}, f"👤 {n}")


def link_card_ref(url: str) -> str:
    """The handle to resolve for a shared t.me link so it opens a card: drop query/fragment and a
    trailing message id (t.me/chan/42 -> t.me/chan); private invites (t.me/+inv) are left intact."""
    u = (url or "").strip().split("?")[0].split("#")[0]
    return _MSGID_TAIL.sub("", u)
