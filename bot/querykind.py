"""Decide what kind of thing a user typed, so handlers can react automatically instead of asking.

The rule is deliberately simple and predictable, and meant to be reused across commands (and future
ones) that take a "person/group" query:

  - all digits                       -> ID       (exact numeric Telegram id)
  - @handle  or  a t.me link         -> USERNAME (explicit marker -> exact username match)
  - anything else (bare word, text)  -> TEXT     (substring search; also catches an exact username
                                                   typed without @, so users don't have to think)

So an explicit marker (@, link, digits) means "match this exactly"; plain text means "search". To
pinpoint one person/group, use @username or the numeric id.
"""
from enum import Enum

from bot.group_links import LINK_USERNAME_RE, normalize_query


class QueryKind(str, Enum):
    ID = "id"
    USERNAME = "username"
    TEXT = "text"


def classify_query(raw: str | None) -> tuple[QueryKind, str]:
    """Return (kind, value): value is the cleaned query to use - digits for ID, the bare handle for
    USERNAME, the trimmed text for TEXT. A bare word with no @/link is TEXT on purpose, so partial
    names work; only the explicit markers (@, link, all-digits) ask for an exact match."""
    q = (raw or "").strip()
    if q.isdigit():
        return QueryKind.ID, q
    if q.startswith("@") or LINK_USERNAME_RE.search(q):
        return QueryKind.USERNAME, normalize_query(q)
    return QueryKind.TEXT, q
