"""Entity card logic (handlers in bot/modules/card.py): detect an entity reference in a message,
resolve it to an identity, and gather its archive state.

The card is a pure launcher: it READS state (live resolve + DB + favorites + check store) and its
buttons trigger the existing flows (check / favorites / members / links). It adds no storage and no
DB writer - nothing here changes CSV/watcher/transfer behaviour.
"""
import json
from dataclasses import dataclass

from bot.entitykind import BOT, CHANNEL, GROUP, USER, classify_entity, entity_display, entity_username
from bot.favorites import RateLimited, ResolvedTarget, TelegramLookupUnavailable, _from_group_row, parse_favorite_arg, resolve_target
from bot.group_links import LINK_USERNAME_RE, USERNAME_RE
from bot.pagination import get_token, store_token
from bot.telethon_client import get_scrape_client
from collectors import check
from collectors.resolve import invite_hash, invite_preview
from collectors.throttle import floodwait_seconds
from db.queries import groups as groups_q
from db.queries import links as links_q
from db.queries import members as members_q


def parse_entity_ref(text: str | None) -> str | None:
    """A single-token @username / t.me link / t.me/+invite / numeric id -> the string to resolve.
    Anything else (free text, multiple words) -> None, so the handler shows a hint instead."""
    text = (text or "").strip()
    if not text or " " in text or "\n" in text:
        return None
    if invite_hash(text):                              # private invite link
        return text
    if LINK_USERNAME_RE.search(text):                  # t.me/<username>
        return text
    if text.startswith("@") and USERNAME_RE.match(text[1:]):
        return text
    if text.lstrip("-").isdigit():                     # numeric id
        return text
    return None


def _identity_from_entity(entity) -> ResolvedTarget | None:
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


async def resolve_identity(pool, resolve_input: str, get_client=get_scrape_client) -> ResolvedTarget | None:
    """Identify a pasted target. Private invite links go through resolve_entity (which handles them);
    everything else reuses favorites.resolve_target (Telegram-first, archive fallback). get_client is
    the bot's client by default; the CLI passes its own. None = can't resolve or classify."""
    hash_ = invite_hash(resolve_input)
    if hash_:
        # Archive-first: a private group we already know (matched by its invite hash) opens from the DB
        # with NO Telegram call. Then the 24h resolve cache, so reopening an unsaved invite is free too.
        row = await groups_q.find_group_by_invite_hash(pool, hash_)
        if row is not None:
            return _from_group_row(row)
        from bot import resolve_cache
        from collectors.resolve import is_dead_reference
        key = f"invite:{hash_}"
        cached = resolve_cache.get(key)
        if cached is resolve_cache.NEGATIVE:
            return None
        if cached is not None:
            return cached
        try:
            client = await get_client()
        except RuntimeError as e:
            # The client is off (session not authorized/reconnecting) - that's not "this invite is
            # dead", so say so instead of a generic not-found (the caller shows check_unavailable).
            raise TelegramLookupUnavailable(str(e)) from e
        try:
            # invite_preview (not resolve_entity): a VALID invite the account hasn't joined still yields
            # a card - only revoked/expired ones return None here.
            target = _identity_from_entity(await invite_preview(client, hash_))
        except Exception as e:
            secs = floodwait_seconds(e)
            if secs is not None:  # a FloodWait isn't a dead invite - surface the wait to the caller
                raise RateLimited(secs) from e
            if is_dead_reference(e):  # revoked/expired invite -> remember, so reopening it is free
                resolve_cache.put(key, resolve_cache.NEGATIVE)
            return None  # revoked/expired invite
        if target is None:
            return None
        # A private group has no public link: keep the invite link so the card links out and
        # archive_state can match the DB row by its invite hash.
        if not target.link:
            target.link = resolve_input if resolve_input.lower().startswith("http") else f"https://t.me/+{hash_}"
        resolve_cache.put(key, target)  # remember it for 24h so reopening the same invite is free
        return target

    parsed = parse_favorite_arg(resolve_input)
    if parsed is None:
        return None
    # TelegramLookupUnavailable (client off) and RateLimited propagate to the caller, which shows the
    # real reason instead of a generic "not found" - this WAS silently swallowed into None here.
    return await resolve_target(pool, get_client, parsed)


# --- archive state ------------------------------------------------------------------------------

@dataclass
class CardState:
    in_archive: bool = False
    group_id: int | None = None
    members: int = 0
    links: int = 0
    groups: int = 0            # for a user: how many groups they're in
    is_favorite: bool = False
    check_status: str | None = None
    check_entry: dict | None = None


def _fav_match(item: dict, target: ResolvedTarget) -> bool:
    if target.username and item.get("username") and item["username"].lower() == target.username.lower():
        return True
    if target.tg_id is not None and item.get("tg_id") == target.tg_id:
        return True
    # A private group has no username/id - match it by its invite link so it can be (un)favorited too.
    return bool(target.link) and item.get("link") == target.link


async def archive_state(pool, target: ResolvedTarget) -> CardState:
    from bot import favorites_store

    state = CardState()

    if target.kind in (GROUP, CHANNEL):
        row = None
        if target.username:
            row = await groups_q.find_group_by_exact_username(pool, target.username)
        if row is None and target.tg_id is not None:
            row = await groups_q.find_group_by_chat_id(pool, target.tg_id)
        if row is None and target.link:  # private group: match the DB row by its invite hash
            row = await groups_q.find_group_by_invite_hash(pool, invite_hash(target.link) or "")
        if row is not None:
            state.in_archive = True
            state.group_id = row["id"]
            state.members = row["members"] if "members" in row.keys() else 0
            state.links = row["links"] if "links" in row.keys() else 0
    elif target.kind in (USER, BOT):
        mem = None
        if target.username:
            mem = await members_q.find_member(pool, username=target.username)
        if mem is None and target.tg_id is not None:
            mem = await members_q.find_member(pool, tg_user_id=target.tg_id)
        if mem is not None:
            state.in_archive = True
            uid = mem["tg_user_id"]
            state.groups = len(await members_q.find_member_groups(pool, str(uid)))
            state.links = len(await links_q.links_by_user(pool, uid))

    state.is_favorite = any(_fav_match(i, target) for i in favorites_store.load(target.kind))

    entry = check.load_status().get(check.status_key(
        target.kind, title=target.title or "", username=target.username, link=target.link, tg_id=target.tg_id))
    if entry:
        state.check_entry = entry
        state.check_status = entry.get("status")

    return state


# --- identity <-> token (so a button carries a tiny reference, not the whole identity) -----------

def pack_token(target: ResolvedTarget, back: str | None = None) -> str:
    """Store the identity in a token. `back` (a callback the card's top-level Back should fire) is
    carried along so it survives the card's own in-place navigation."""
    return store_token(json.dumps({
        "kind": target.kind, "tg_id": target.tg_id, "username": target.username,
        "title": target.title, "link": target.link, "back": back,
    }))


def unpack_token(token: str) -> ResolvedTarget | None:
    raw = get_token(token)
    if not raw:
        return None
    try:
        d = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    return ResolvedTarget(kind=d["kind"], tg_id=d.get("tg_id"), username=d.get("username"),
                          title=d.get("title"), link=d.get("link"))


def back_of(token: str) -> str | None:
    """The card's top-level Back callback stored in the token, or None."""
    raw = get_token(token)
    if not raw:
        return None
    try:
        return json.loads(raw).get("back")
    except (json.JSONDecodeError, TypeError):
        return None


def target_resolve_input(target: ResolvedTarget) -> str | None:
    """What to hand a scraper/checker for this identity: its link, else @handle, else numeric id."""
    if target.link:
        return target.link
    if target.username:
        return f"@{target.username}"
    return str(target.tg_id) if target.tg_id is not None else None
