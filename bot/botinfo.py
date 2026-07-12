"""The bot's own @username, needed to build t.me deep links.

Inline text can't carry a callback, so the clickable user/link counts in the hub's group lists
are t.me/<bot>?start=<payload> deep links: tapping one sends `/start <payload>`, which bot/modules/
start.py turns into the members/links view. The username is filled in once at startup (bot.get_me);
until then deep_link() returns None and callers fall back to plain (non-clickable) text.
"""
_bot_username: str | None = None


def set_bot_username(username: str | None) -> None:
    global _bot_username
    _bot_username = username


def deep_link(payload: str) -> str | None:
    return f"https://t.me/{_bot_username}?start={payload}" if _bot_username else None
