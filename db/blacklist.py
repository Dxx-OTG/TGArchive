import re
from dataclasses import dataclass

from Blacklist import GROUPS_BLACKLIST, USER_IDS_BLACKLIST, USERNAMES_BLACKLIST

_LINK_PREFIX_RE = re.compile(r"^https?://(t\.me|telegram\.me)/", re.IGNORECASE)


def _normalize(value: str) -> str:
    """So that 'name', '@name', 't.me/name' and 'https://t.me/name' all map to the same group."""
    value = _LINK_PREFIX_RE.sub("", value.strip().lower())
    return value.lstrip("@")


_USERNAMES = {_normalize(u) for u in USERNAMES_BLACKLIST}
_USER_IDS = set(USER_IDS_BLACKLIST)
_GROUPS = {_normalize(g) for g in GROUPS_BLACKLIST}


def is_user_blacklisted(tg_user_id: int | None, username: str | None) -> bool:
    if tg_user_id is not None and tg_user_id in _USER_IDS:
        return True
    return bool(username) and _normalize(username) in _USERNAMES


def is_group_blacklisted(*, title: str | None = None, username: str | None = None, invite_input: str | None = None) -> bool:
    for value in (title, username, invite_input):
        if value and _normalize(value) in _GROUPS:
            return True
    return False


def is_favorite_blacklisted(row: dict) -> bool:
    """A saved-favorite row ({kind, tg_id, username, title, link}) that is now blacklisted, so it
    should vanish from the favorites listing too - blacklisted means 'as if it doesn't exist'."""
    if row.get("kind") == "user":
        return is_user_blacklisted(row.get("tg_id"), row.get("username"))
    return is_group_blacklisted(title=row.get("title"), username=row.get("username"), invite_input=row.get("link"))


@dataclass(frozen=True)
class ResolvedBlacklist:
    """Concrete DB row ids to exclude everywhere. Empty lists = nothing to hide (Postgres treats
    `x != ALL('{}')` as true, so empty arrays are a cheap no-op in every query)."""
    group_ids: list[int]
    member_ids: list[int]
    link_ids: list[int]


def blacklist_active() -> bool:
    return bool(_USER_IDS or _USERNAMES or _GROUPS)


async def resolve_blacklist(pool) -> ResolvedBlacklist:
    """Resolve the static blacklist (Blacklist.py) to the concrete ids of the groups, members and
    extracted links to exclude. A link is blacklisted if it lives in a blacklisted group, was sent by
    a blacklisted user, or points to a blacklisted group/channel. Returns empty lists WITHOUT touching
    the DB when the blacklist is unset (the common case). Queries pass these arrays so counts AND lists
    exclude the exact same rows - a blacklisted entity is then invisible in every count and result."""
    if not blacklist_active():
        return ResolvedBlacklist([], [], [])

    group_rows = await pool.fetch("SELECT id, title, username, invite_input FROM groups")
    group_ids = [
        r["id"] for r in group_rows
        if is_group_blacklisted(title=r["title"], username=r["username"], invite_input=r["invite_input"])
    ]

    member_rows = await pool.fetch("SELECT id, tg_user_id, username FROM members")
    member_ids = [r["id"] for r in member_rows if is_user_blacklisted(r["tg_user_id"], r["username"])]

    group_set = set(group_ids)
    link_rows = await pool.fetch("SELECT id, group_id, sender_user_id, sender_username, link FROM extracted_links")
    link_ids = [
        r["id"] for r in link_rows
        if r["group_id"] in group_set
        or is_user_blacklisted(r["sender_user_id"], r["sender_username"])
        or is_group_blacklisted(invite_input=r["link"])
    ]

    return ResolvedBlacklist(group_ids, member_ids, link_ids)
