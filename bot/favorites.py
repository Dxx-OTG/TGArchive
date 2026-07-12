"""Favorites resolution and rendering, used by the entity card (save/unsave) and the /start hub's
Favorites view (bot/modules/start.py)."""
from dataclasses import dataclass
from html import escape

from bot.entitykind import BOT, CHANNEL, GROUP, USER, classify_entity, entity_display, entity_username, is_bot_username
from bot.group_links import USERNAME_RE, extract_username, group_link, normalize_query
from bot.i18n import plural, t
from collectors.throttle import floodwait_seconds
from db.queries import groups as groups_q
from db.queries import members as members_q

# Cap per section; the listing isn't paginated.
FAV_CAP = 100


class TelegramLookupUnavailable(Exception):
    """An unknown handle needs a Telegram resolve but the client is off. Carries a user-facing reason."""


class RateLimited(Exception):
    """A live lookup hit a Telegram FloodWait. `seconds` is how long to wait (0 if unknown), so the
    caller can show the exact time instead of a generic 'not found'."""

    def __init__(self, seconds: int = 0):
        super().__init__(f"FloodWait {seconds}s")
        self.seconds = seconds


@dataclass
class ResolvedTarget:
    kind: str
    tg_id: int | None
    username: str | None
    title: str | None
    link: str | None


def parse_favorite_arg(raw: str | None) -> tuple[str, object] | None:
    """('id', int), ('username', handle), or None when it isn't a single target."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.isdigit():
        return ("id", int(raw))
    handle = normalize_query(raw)
    if USERNAME_RE.match(handle):
        return ("username", handle)
    return None


def _from_group_row(row) -> ResolvedTarget:
    return ResolvedTarget(
        kind=CHANNEL if row.get("kind") == "channel" else GROUP,
        tg_id=row["tg_chat_id"],
        username=extract_username(row["username"], row["invite_input"]),
        title=row["title"],
        link=group_link(row["username"], row["invite_input"]),
    )


def _from_member_row(row) -> ResolvedTarget:
    username = row["username"]
    return ResolvedTarget(
        kind=BOT if is_bot_username(username) else USER,  # a bot is a user whose @username ends in 'bot'
        tg_id=row["tg_user_id"],
        username=username,
        title=f"@{username}" if username else None,
        link=f"https://t.me/{username}" if username else None,
    )


def _from_entity(entity) -> ResolvedTarget | None:
    kind = classify_entity(entity)
    if kind is None:
        return None
    username = entity_username(entity)
    return ResolvedTarget(
        kind=kind,
        tg_id=getattr(entity, "id", None),
        username=username,
        title=entity_display(entity),
        link=f"https://t.me/{username}" if username else None,
    )


async def _resolve_local(pool, mode: str, value) -> ResolvedTarget | None:
    """Classify against the archive only, no Telegram call."""
    if mode == "username":
        grp = await groups_q.find_group_by_exact_username(pool, value)
        if grp is not None:
            return _from_group_row(grp)
        mem = await members_q.find_member(pool, username=value)
        if mem is not None:
            return _from_member_row(mem)
    else:
        mem = await members_q.find_member(pool, tg_user_id=value)
        if mem is not None:
            return _from_member_row(mem)
        grp = await groups_q.find_group_by_chat_id(pool, value)
        if grp is not None:
            return _from_group_row(grp)
    return None


async def resolve_target(pool, get_client, parsed: tuple[str, object]) -> ResolvedTarget | None:
    """Archive-first: if the entity is already in the DB, use that identity (its kind included) with NO
    Telegram call - only handles we've never seen need a live resolve. This keeps opening a known card
    or tapping a name in a list free of ResolveUsername requests (what Telegram rate-limits hardest).
    Raises TelegramLookupUnavailable when the client is off and the archive has nothing; RateLimited on
    a FloodWait. None = genuinely not found."""
    from bot import favorites_store, resolve_cache
    mode, value = parsed

    # Local sources first, each with zero API calls: the archive (DB), then favorites (they carry their
    # own identity, so a favorited entity never costs a call even when it isn't archived).
    local = await _resolve_local(pool, mode, value)
    if local is not None:
        return local
    fav = favorites_store.find(username=value if mode == "username" else None,
                               tg_id=value if mode == "id" else None)
    if fav is not None:
        return fav

    # Then the 24h resolve cache, so reopening a link that was resolved before (but never saved) is free
    # - including a genuinely-dead handle remembered as NEGATIVE, so reopening it doesn't re-call either.
    key = f"{mode}:{value}"
    cached = resolve_cache.get(key)
    if cached is resolve_cache.NEGATIVE:
        return None
    if cached is not None:
        return cached

    try:
        client = await get_client()
    except RuntimeError as e:
        raise TelegramLookupUnavailable(str(e)) from e

    try:
        entity = await client.get_entity(value)
    except Exception as e:
        # A FloodWait isn't "not found" - surface it (with the wait) so the caller can say so.
        secs = floodwait_seconds(e)
        if secs is not None:
            raise RateLimited(secs) from e
        from bot.log import log  # the REAL reason (UsernameInvalid, ChannelPrivate, …), else it looks like "not found"
        log(f"⚠️ card resolve of '{value}' via Telegram failed: {type(e).__name__}: {e}")
        from collectors.resolve import is_dead_reference
        if is_dead_reference(e):  # genuinely gone -> remember, so reopening a dead link is free
            resolve_cache.put(key, resolve_cache.NEGATIVE)
        return None
    target = _from_entity(entity)
    if target is not None:
        resolve_cache.put(key, target)  # remember it for 24h so reopening the same link is free
    return target


# --- rendering ----------------------------------------------------------------------------------

def _entity_line(row, linker=None) -> str:
    """A favorite group/channel. With `linker` the name opens the entity's CARD in place (Back ->
    favorites); without it, plain text - never a direct chat link (only the card links out)."""
    title = row["title"] or row["username"] or "?"
    if linker:
        handle = row["link"] or (f"@{row['username']}" if row["username"] else title)
        return f"   • {linker(handle, title)}"
    return f"   • {escape(title)}"


def _user_line(row, linker=None) -> str:
    username = row["username"]
    label = f"@{username}" if username else (row["title"] or str(row["tg_id"]))
    if linker:
        handle = f"@{username}" if username else str(row["tg_id"])
        return f"   • {linker(handle, label)}"
    if username or row["title"]:
        return f"   • {escape(label)}"
    return f'   • <code>{row["tg_id"]}</code>'


def render_favorites(groups: list, channels: list, users: list, bots: list, linker=None) -> str:
    """The Favorites listing: groups, channels, users, then bots, each section capped with a '+N more'.
    `linker` (name -> in-place card link) makes every entry open its card; None = plain text."""
    lines = [t("favorites_header")]
    if groups:
        lines.append(t("favorites_groups_section", n=len(groups), word=plural(len(groups), "Group", "Groups")))
        lines.extend(_entity_line(r, linker) for r in groups[:FAV_CAP])
        if len(groups) > FAV_CAP:
            lines.append(t("list_more", n=len(groups) - FAV_CAP))
    if channels:
        lines.append(t("favorites_channels_section", n=len(channels), word=plural(len(channels), "Channel", "Channels")))
        lines.extend(_entity_line(r, linker) for r in channels[:FAV_CAP])
        if len(channels) > FAV_CAP:
            lines.append(t("list_more", n=len(channels) - FAV_CAP))
    if users:
        lines.append(t("favorites_users_section", n=len(users), word=plural(len(users), "User", "Users")))
        lines.extend(_user_line(r, linker) for r in users[:FAV_CAP])
        if len(users) > FAV_CAP:
            lines.append(t("list_more", n=len(users) - FAV_CAP))
    if bots:
        lines.append(t("favorites_bots_section", n=len(bots), word=plural(len(bots), "Bot", "Bots")))
        lines.extend(_user_line(r, linker) for r in bots[:FAV_CAP])
        if len(bots) > FAV_CAP:
            lines.append(t("list_more", n=len(bots) - FAV_CAP))
    return "\n".join(lines)
