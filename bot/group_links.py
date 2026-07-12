import re
from typing import Callable, TypeVar

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")
LINK_USERNAME_RE = re.compile(r"(?:t\.me|telegram\.me)/([A-Za-z0-9_]{5,32})/?$", re.IGNORECASE)

_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)
_TME_DOMAIN_RE = re.compile(r"^(?:www\.)?(?:t\.me|telegram\.me)/", re.IGNORECASE)

# t.me paths that are NOT a user/channel/group handle (service links, message ids, previews, …). We
# only archive links that point to an entity, so these are dropped (except the invite forms below).
_RESERVED_TME = {
    "s", "c", "addstickers", "addemoji", "addlist", "proxy", "socks", "share", "setlanguage",
    "bg", "iv", "confirmphone", "login", "boost", "giftcode", "joinchat",
}

LINK_KEY_RE = re.compile(r"/\d+/?$")


def link_key(link: str) -> str:
    """Dedup key shared by the CSV scraper and the DB layer: lowercase, then drop a trailing message
    ID (e.g. /2137) so message links to the same entity collapse to one key. Lives here - the single
    link-helper module both sides import - so CSV dedup and DB dedup can never drift apart."""
    return LINK_KEY_RE.sub("", link.lower())


def normalize_entity_link(link: str | None) -> str | None:
    """Reduce a t.me link to the ENTITY it points to, or None when it isn't a link to a user / channel
    / group. Drops the message/discussion id (t.me/x/123 -> t.me/x), queries and previews, and
    Telegram service paths (t.me/c/…, addstickers, proxy, share, …). Keeps public @usernames and
    private invites (t.me/+HASH, t.me/joinchat/HASH). Used at scrape and import so the archive holds
    only real entity links and message links to the same entity dedupe instead of piling up."""
    raw = (link or "").strip()
    if not re.match(r"^(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me)/", raw, re.IGNORECASE):
        return None
    path = _TME_DOMAIN_RE.sub("", _SCHEME_RE.sub("", raw))  # path after the t.me/ host
    path = path.split("?")[0].split("#")[0].strip("/")
    if not path:
        return None
    if path.startswith("+"):                            # private invite t.me/+HASH
        h = path.split("/")[0]
        return f"https://t.me/{h}" if len(h) > 1 else None
    parts = path.split("/")
    head = parts[0].lower()
    if head == "joinchat" and len(parts) >= 2 and parts[1]:   # invite t.me/joinchat/HASH
        return f"https://t.me/joinchat/{parts[1]}"
    if head == "s" and len(parts) >= 2:                       # public preview t.me/s/username -> the channel
        parts = parts[1:]
    handle = parts[0]
    if handle.lower() in _RESERVED_TME or not USERNAME_RE.match(handle):
        return None                                    # service path, /c/ message link, invalid handle
    return f"https://t.me/{handle}"


def link_display(url: str) -> str:
    """The clean, human-readable name of a link for list display: drop the scheme and the
    t.me/telegram.me domain, leaving just the path ('durov', 'durov/42', '+AbCd', 'joinchat/x').
    The full url is kept only as the click target; this is what the user reads. Empty/odd input
    falls back to the raw url so a link is never shown blank."""
    s = _SCHEME_RE.sub("", (url or "").strip())
    s = _TME_DOMAIN_RE.sub("", s)
    return (s.rstrip("/") or (url or "").strip() or url)


def extract_username(username: str | None, invite_input: str | None) -> str | None:
    """Get the group's public username, from the dedicated column or from invite_input in any of
    its forms: 'name', '@name', 't.me/name', 'https://t.me/name'."""
    if username:
        return username

    invite = (invite_input or "").strip()
    if not invite:
        return None

    match = LINK_USERNAME_RE.search(invite)
    if match:
        return match.group(1)

    bare = invite.lstrip("@")
    if USERNAME_RE.match(bare):
        return bare

    return None


def normalize_query(value: str) -> str:
    """Extract the bare username from a user-typed query in any format (name, @name, t.me/name,
    https://t.me/name). Free text with no recognized format is returned as-is, minus a leading @."""
    value = value.strip()
    match = LINK_USERNAME_RE.search(value)
    if match:
        return match.group(1)
    return value.lstrip("@")


def group_link(username: str | None, invite_input: str | None) -> str | None:
    handle = extract_username(username, invite_input)
    if handle:
        return f"https://t.me/{handle}"

    # Private invite link (joinchat/HASH or +HASH): not a username, keep it as-is.
    invite = (invite_input or "").strip()
    if invite.startswith("http://") or invite.startswith("https://"):
        return invite

    return None


Row = TypeVar("Row")


def canonical_group_key(title: str, username: str | None = None, invite_input: str | None = None) -> str:
    """Canonical identity of a group, used everywhere (display, creation, merge, prune): same real
    link or, failing that, same title - always lowercased."""
    return (group_link(username, invite_input) or title).strip().lower()


def _canonical_key(row: Row, link_fn: Callable[[Row], str | None]) -> str:
    return (link_fn(row) or row["title"]).strip().lower()


def dedupe_groups(
    rows: list[Row],
    *,
    link_fn: Callable[[Row], str | None],
    score_fn: Callable[[Row], int] = lambda _row: 0,
) -> list[Row]:
    """The same group can appear as distinct rows (e.g. from Groups vs Messages with a different
    invite_input). Group by canonical link (fallback: title) and keep the highest-score row per
    identity, in first-appearance order."""
    best_by_key: dict[str, Row] = {}
    order: list[str] = []

    for row in rows:
        key = _canonical_key(row, link_fn)
        current = best_by_key.get(key)
        if current is None:
            order.append(key)
            best_by_key[key] = row
        elif score_fn(row) > score_fn(current):
            best_by_key[key] = row

    return [best_by_key[key] for key in order]
