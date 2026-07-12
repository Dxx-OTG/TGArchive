"""Reachability check for archived and favorited entities (Check All in the hub, and the card).

Probes whether a group/channel/user is still reachable on Telegram (deleted, banned, private, invite
expired, …). The result is kept in a small JSON side-file, output/.check_status.json, NOT the
database, for three reasons that all point the same way:
  - favorites live outside the DB (and must stay there), yet must be checkable;
  - an ad-hoc single check can target something with no DB row at all;
  - the CSV watcher is the *only* DB writer - a file store keeps these consistent and leaves the
    schema untouched (no migration).
The file is a dot-file at the output/ root, so the watcher, Export All and Delete All (all
`*.csv`-scoped) never touch it. Status is cheaply re-derivable by re-running Check All.

telethon imports are done lazily inside the probing functions so the store / target-building /
TTL logic stays importable (and unit-testable) without telethon installed.
"""
import asyncio
import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.entitykind import BOT, CHANNEL, GROUP, USER, is_bot_username
from bot.group_links import canonical_group_key, extract_username, group_link


def _leaf_kind(username: str | None) -> str:
    """USER, or BOT when the @username ends in 'bot' (a bot is a user, classified locally)."""
    return BOT if is_bot_username(username) else USER
from collectors.throttle import CHECK_STATUS_TTL_HOURS, MAX_CHECK_PER_RUN, MAX_FLOOD_WAIT, check_sleep_seconds

STATUS_FILE = Path("output") / ".check_status.json"

# Reachability outcomes.
STATUS_OK = "ok"
STATUS_NOT_FOUND = "not_found"            # username freed / entity or account deleted / no such peer
STATUS_PRIVATE = "private"                # exists but not reachable by this account (banned/kicked/private)
STATUS_INVITE_INVALID = "invite_invalid"  # a private invite link expired or was revoked
STATUS_RESTRICTED = "restricted"          # taken down by Telegram for a ToS violation ("Not available")
STATUS_ERROR = "error"                    # transient (FloodWait/network/RPC/unresolvable) - NOT proof of death

# Confirmed-dead statuses: rendered ❌ and eligible for "remove inactive". STATUS_ERROR is
# deliberately excluded - a transient failure must never delete anything.
DEAD_STATUSES = frozenset({STATUS_NOT_FOUND, STATUS_PRIVATE, STATUS_INVITE_INVALID, STATUS_RESTRICTED})

_GLYPH = {
    STATUS_OK: "✅",
    STATUS_NOT_FOUND: "❌",
    STATUS_PRIVATE: "❌",
    STATUS_INVITE_INVALID: "❌",
    STATUS_RESTRICTED: "❌",
    STATUS_ERROR: "⚠️",
}
UNCHECKED_GLYPH = "▫️"


def status_glyph(status: str | None) -> str:
    """The single emoji shown next to an entity: ✅ reachable, ❌ dead, ⚠️ couldn't verify (transient),
    ▫️ not checked yet. The fuller meaning is spelled out in the ℹ️ Help guide, per the design."""
    return _GLYPH.get(status or "", UNCHECKED_GLYPH)


def is_dead(status: str | None) -> bool:
    return status in DEAD_STATUSES


# --- target model -------------------------------------------------------------------------------

@dataclass
class CheckTarget:
    """One thing to probe. `canonical_key` is the shared identity used to index the status store and
    to dedupe a DB group against the same entity saved as a favorite. `resolve_input` is what gets
    handed to Telegram (None = nothing resolvable, e.g. a title-only group -> can't verify)."""
    kind: str                    # USER / GROUP / CHANNEL
    canonical_key: str
    title: str
    link: str | None
    resolve_input: str | None
    username: str | None = None
    tg_id: int | None = None
    is_favorite: bool = False


def _group_canonical(title: str, username: str | None, link_or_invite: str | None) -> str:
    return canonical_group_key(title, username, link_or_invite)


def _user_canonical(tg_id: int | None, username: str | None) -> str:
    if tg_id:
        return f"user:{tg_id}"
    return f"user:{(username or '').strip().lower()}"


def status_key(kind: str, *, title: str = "", username: str | None = None,
               link: str | None = None, tg_id: int | None = None) -> str:
    """The status-store key for an entity, the single source of truth shared with the Check All
    targets so a card and a bulk run point at the same stored result."""
    if kind in (USER, BOT):  # a bot is keyed like a user (user:<id>/user:<username>)
        return _user_canonical(tg_id, username)
    return _group_canonical(title or "", username, link)


def target_from_group_row(row) -> CheckTarget:
    """Build a target from a DB groups row (id/title/username/invite_input/kind, tg_chat_id optional)."""
    username = extract_username(row["username"], row["invite_input"])
    link = group_link(row["username"], row["invite_input"])
    tg_id = row["tg_chat_id"] if "tg_chat_id" in row.keys() else None
    resolve_input = link or (str(tg_id) if tg_id else None)
    return CheckTarget(
        kind=CHANNEL if row["kind"] == "channel" else GROUP,
        canonical_key=_group_canonical(row["title"], row["username"], row["invite_input"]),
        title=row["title"],
        link=link,
        resolve_input=resolve_input,
        username=username,
        tg_id=tg_id,
    )


def target_from_favorite(kind: str, item: dict) -> CheckTarget:
    """Build a target from a favorites_store item (kind/tg_id/username/title/link)."""
    username = item.get("username")
    tg_id = item.get("tg_id")
    link = item.get("link")
    if kind in (USER, BOT):
        if not link and username:
            link = f"https://t.me/{username}"
        title = item.get("title") or (f"@{username}" if username else str(tg_id))
        return CheckTarget(
            kind=_leaf_kind(username),  # a favorited bot is a leaf like a user, bucketed under Bots
            canonical_key=_user_canonical(tg_id, username),
            title=title,
            link=link,
            resolve_input=(f"@{username}" if username else (str(tg_id) if tg_id else None)),
            username=username, tg_id=tg_id, is_favorite=True,
        )
    if not link and username:
        link = group_link(username, None)
    title = item.get("title") or (f"@{username}" if username else (str(tg_id) if tg_id else "?"))
    return CheckTarget(
        kind=CHANNEL if kind == CHANNEL else GROUP,
        canonical_key=_group_canonical(title, username, link),
        title=title,
        link=link,
        resolve_input=link or (f"@{username}" if username else (str(tg_id) if tg_id else None)),
        username=username, tg_id=tg_id, is_favorite=True,
    )


def target_from_entity(entity, invite_link: str | None = None) -> CheckTarget:
    """Build a target from a freshly resolved Telethon entity (for a single check on something not
    yet in the archive). `invite_link` is the original t.me/+HASH link when the input was a private
    invite: a private group has no public username/link, so without it the canonical key would fall
    back to the title and NOT match the key the card/`Check All` use (built from invite_input) -
    the stored result would then be invisible to the card."""
    from bot.entitykind import classify_entity, entity_display, entity_username
    kind = classify_entity(entity) or GROUP
    username = entity_username(entity)
    tg_id = getattr(entity, "id", None)
    title = entity_display(entity) or (f"@{username}" if username else str(tg_id))
    if kind in (USER, BOT):
        link = f"https://t.me/{username}" if username else None
        return CheckTarget(kind, _user_canonical(tg_id, username), title, link,
                           (f"@{username}" if username else (str(tg_id) if tg_id else None)),
                           username, tg_id)
    link = group_link(username, None) or invite_link  # private group -> key off the invite link
    return CheckTarget(kind, _group_canonical(title, username, link), title, link,
                       link or (f"@{username}" if username else (str(tg_id) if tg_id else None)),
                       username, tg_id)


def _target_from_raw(raw: str) -> CheckTarget | None:
    """A best-effort identity for a target that failed to resolve, so a single check can still store
    and show a ❌ with a clickable handle."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.lstrip("-").isdigit():  # a bare numeric id isn't a username, and has no public link
        return CheckTarget(GROUP, _group_canonical(raw, None, raw), raw, None, raw, None, int(raw))
    username = extract_username(None, raw)
    if username:
        if is_bot_username(username):  # a @…bot handle is a bot (leaf), keyed like a user
            return CheckTarget(BOT, _user_canonical(None, username), f"@{username}",
                               f"https://t.me/{username}", f"@{username}", username, None)
        return CheckTarget(GROUP, _group_canonical(raw, username, raw), f"@{username}",
                           f"https://t.me/{username}", f"@{username}", username, None)
    link = raw if raw.startswith("http") else None
    return CheckTarget(GROUP, _group_canonical(raw, None, raw), raw, link, raw, None, None)


def sort_targets(targets: list[CheckTarget]) -> list[CheckTarget]:
    """Favorites first (they go on top of each list), then alphabetical by title."""
    return sorted(targets, key=lambda t: (not t.is_favorite, (t.title or "").lower()))


async def gather_targets(pool) -> list[CheckTarget]:
    """Everything `Check All` probes: favorite users/groups/channels (curated - the huge members
    table is deliberately out of scope) plus every scraped group and channel. Favorites are added
    first so a favorite that's also a scraped group wins the row (is_favorite -> sorted on top).
    Blacklisted entities are dropped."""
    from bot import favorites_store
    from db.blacklist import is_favorite_blacklisted
    from db.queries import groups as groups_q

    by_key: dict[str, CheckTarget] = {}
    for kind in (GROUP, CHANNEL, USER, BOT):
        for item in favorites_store.load(kind):
            if is_favorite_blacklisted(item):
                continue
            tgt = target_from_favorite(kind, item)
            by_key.setdefault(tgt.canonical_key, tgt)

    for kind in ("group", "channel"):
        for row in await groups_q.list_groups_with_counts(pool, kind):
            tgt = target_from_group_row(row)
            by_key.setdefault(tgt.canonical_key, tgt)

    return list(by_key.values())


# --- status store -------------------------------------------------------------------------------

def load_status() -> dict[str, dict]:
    if not STATUS_FILE.exists():
        return {}
    try:
        data = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_status(data: dict[str, dict]) -> None:
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATUS_FILE.with_suffix(".json.new")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATUS_FILE)


def is_fresh(entry: dict, now: datetime | None = None) -> bool:
    """True if this stored result is younger than the TTL, so `Check All` reuses it instead of
    re-probing (unless forced)."""
    now = now or datetime.now(timezone.utc)
    ts = entry.get("checked_at")
    if not ts:
        return False
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt) < timedelta(hours=CHECK_STATUS_TTL_HOURS)


def _entry(tgt: CheckTarget, status: str, now: datetime, kind: str | None = None) -> dict:
    # title/link/kind are cached so favorites and ad-hoc targets render even without a DB row. kind
    # falls back to the target's declared kind; for a link target (kind is unknown until resolved) the
    # probe-discovered kind is what lets Check Links group its results by user/channel/group.
    return {"status": status, "checked_at": now.isoformat(), "title": tgt.title, "link": tgt.link, "kind": kind or tgt.kind}


def age_text(entry: dict | None) -> str:
    """A short 'when was this last checked' label ('3m ago', '5h ago', '2d ago', or 'never')."""
    ts = (entry or {}).get("checked_at")
    if not ts:
        return "never"
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return "never"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = (datetime.now(timezone.utc) - dt).total_seconds()
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    return f"{int(secs // 86400)}d ago"


# --- probing (telethon) -------------------------------------------------------------------------

def classify_reachability(exc: Exception) -> str:
    """Map a resolve exception to a dead/transient status. FloodWait is handled by the caller."""
    from telethon import errors
    if isinstance(exc, (errors.UsernameNotOccupiedError, errors.UsernameInvalidError)):
        return STATUS_NOT_FOUND
    if isinstance(exc, errors.ChannelPrivateError):
        return STATUS_PRIVATE
    if isinstance(exc, (errors.InviteHashExpiredError, errors.InviteHashInvalidError)):
        return STATUS_INVITE_INVALID
    # get_entity raises ValueError ("Cannot find any entity …", "No user has … as username") for a
    # freed or never-existing public handle.
    if isinstance(exc, ValueError):
        return STATUS_NOT_FOUND
    return STATUS_ERROR


async def _resolve_probe(client, resolve_input: str):
    """Resolve one target. A numeric id goes straight to get_entity (invite-hash parsing is for
    links only); everything else via resolve_entity, which also handles private invites."""
    from collectors.resolve import resolve_entity
    if isinstance(resolve_input, str) and resolve_input.lstrip("-").isdigit():
        return await client.get_entity(int(resolve_input))
    return await resolve_entity(client, resolve_input)


async def _status_from_entity(client, entity) -> str:
    """Turn an already-resolved entity into a STATUS_*. Resolving only proves the entity EXISTS; for a
    group/channel it does NOT prove this account can read it (a public @username resolves even when
    you're banned or it went private, and a peer cached from an earlier scrape can resolve with no
    network hit at all). So a banned entity that comes back as a *Forbidden* type is ❌ outright, and
    any other group/channel gets one lightweight read to confirm real access."""
    from telethon.tl.types import ChannelForbidden, ChatForbidden
    if isinstance(entity, (ChannelForbidden, ChatForbidden)):
        return STATUS_PRIVATE
    # Taken down by Telegram for a ToS violation ("Non disponibile / has violated the ToS"): the entity
    # still resolves as a normal Channel with `restricted=True`, and get_messages can even return old
    # posts, so this flag is the only signal - check it before the read-probe.
    if getattr(entity, "restricted", False):
        return STATUS_RESTRICTED
    if getattr(entity, "deleted", False):  # a deleted account still resolves, as a User(deleted=True)
        return STATUS_NOT_FOUND
    if getattr(entity, "title", None) is not None:  # a group/channel, not a user
        return await _verify_readable(client, entity)
    return STATUS_OK


async def check_invite(client, hash_: str) -> tuple[str, str | None]:
    """Reachability of a PRIVATE invite link WITHOUT joining. resolve_entity is built for SCRAPING, so
    it treats a valid invite this account never joined as an error - but for a CHECK a valid invite
    means the group/channel is ALIVE and reachable (✅), not ❌. So ask CheckChatInvite directly: an
    already-joined chat or a preview -> ✅ (kind from the preview flags); an expired/revoked hash
    raises and maps to ❌ (invite_invalid). Re-raises FloodWaitError."""
    from telethon.errors import FloodWaitError
    from telethon.tl.functions.messages import CheckChatInviteRequest
    from bot.entitykind import classify_entity
    try:
        invite = await client(CheckChatInviteRequest(hash_))
    except FloodWaitError:
        raise
    except Exception as e:
        return classify_reachability(e), None
    chat = getattr(invite, "chat", None)
    if chat is not None:  # already a member (or a temporary peek): confirm we can actually read it
        return await _status_from_entity(client, chat), classify_entity(chat)
    # Preview only (not joined): the invite is valid, so the entity is alive -> reachable.
    return STATUS_OK, CHANNEL if getattr(invite, "broadcast", False) else GROUP


async def check_one(client, resolve_input: str) -> tuple[str, str | None]:
    """Probe one entity -> (STATUS_*, kind). kind is the resolved entity's user/group/channel class
    (None when it couldn't be resolved), so a bulk run can group link targets by what they turned out
    to be. Re-raises FloodWaitError so the caller can decide to stop."""
    from telethon.errors import FloodWaitError
    from collectors.resolve import NotAMemberError, invite_hash
    from bot.entitykind import classify_entity
    hash_ = invite_hash(resolve_input) if isinstance(resolve_input, str) else None
    if hash_ is not None:  # a private invite: judge the invite itself, don't require membership
        return await check_invite(client, hash_)
    try:
        entity = await _resolve_probe(client, resolve_input)
    except FloodWaitError:
        raise
    except NotAMemberError:
        return STATUS_PRIVATE, None
    except Exception as e:
        return classify_reachability(e), None
    return await _status_from_entity(client, entity), classify_entity(entity)


async def _verify_readable(client, entity) -> str:
    """One-message read to tell 'exists' from 'this account can actually access it'. A public channel
    you can still read succeeds (✅); one you were banned from or that went private raises
    ChannelPrivateError -> STATUS_PRIVATE. Re-raises FloodWaitError for the caller."""
    from telethon.errors import FloodWaitError
    try:
        await client.get_messages(entity, limit=1)
    except FloodWaitError:
        raise
    except Exception as e:
        return classify_reachability(e)
    return STATUS_OK


async def _probe_target(client, tgt: CheckTarget) -> tuple[str, str | None, bool, int]:
    """(status, kind, aborted, wait_seconds). aborted=True (with the FloodWait's wait_seconds) means a
    FloodWait over the cap - the whole run should stop and keep what it has (see collectors/retry.py:
    a huge FloodWait *is* the 'back off' signal)."""
    from telethon.errors import FloodWaitError
    if tgt.resolve_input is None:
        return STATUS_ERROR, None, False, 0
    try:
        status, kind = await check_one(client, tgt.resolve_input)
        return status, kind, False, 0
    except FloodWaitError as e:
        seconds = getattr(e, "seconds", 0) or 0
        if seconds > MAX_FLOOD_WAIT:
            return STATUS_ERROR, None, True, seconds
        await asyncio.sleep(seconds)
        try:
            status, kind = await check_one(client, tgt.resolve_input)
            return status, kind, False, 0
        except Exception:
            return STATUS_ERROR, None, False, 0


# --- run result ---------------------------------------------------------------------------------

@dataclass
class CheckRun:
    checked: int = 0
    skipped: int = 0  # reused a fresh stored result instead of re-probing this run
    aborted: bool = False  # stopped early on a floodwait over the cap
    stopped: bool = False  # stopped early by the user's Stop button
    wait_seconds: int = 0  # when aborted: the FloodWait (seconds) Telegram asked for
    capped: bool = False   # hit MAX_CHECK_PER_RUN - some targets left unprobed this run
    remaining: int = 0     # how many were left unprobed by the per-run cap


async def run_check_all(client, targets, *, force: bool = False, on_progress=None, should_stop=None) -> CheckRun:
    """Probe every target, skipping those with a fresh stored result (unless force). Persists the
    store once at the end, including whatever was checked before a stop. on_progress(done, total) is
    awaited after each real probe for a live status message; should_stop() is polled between probes so
    the user's Stop button ends the run while keeping every result gathered so far."""
    store = load_status()
    now = datetime.now(timezone.utc)

    to_probe: list[CheckTarget] = []
    skipped = 0
    for tgt in targets:
        prev = store.get(tgt.canonical_key)
        if not force and prev and is_fresh(prev, now):
            skipped += 1
        else:
            to_probe.append(tgt)

    # Oldest-checked (and never-checked) first, so re-running keeps making progress instead of
    # re-probing the same head of the list, then cap the run to protect the account from a FloodWait.
    to_probe.sort(key=lambda tgt: (store.get(tgt.canonical_key) or {}).get("checked_at") or "")
    remaining = max(0, len(to_probe) - MAX_CHECK_PER_RUN)
    if remaining:
        to_probe = to_probe[:MAX_CHECK_PER_RUN]

    checked = 0
    aborted = False
    stopped = False
    wait_seconds = 0
    for i, tgt in enumerate(to_probe):
        if should_stop is not None and should_stop():
            stopped = True
            break
        status, kind, aborted, wait_seconds = await _probe_target(client, tgt)
        if aborted:
            break
        store[tgt.canonical_key] = _entry(tgt, status, now, kind)
        checked += 1
        if on_progress is not None:
            await on_progress(checked, len(to_probe))
        if i < len(to_probe) - 1:
            await asyncio.sleep(check_sleep_seconds())

    save_status(store)
    # Only report "capped" if the run actually got through its batch (not stopped/aborted first).
    capped = remaining > 0 and not stopped and not aborted
    return CheckRun(checked=checked, skipped=skipped, aborted=aborted, stopped=stopped,
                    wait_seconds=wait_seconds, capped=capped, remaining=remaining)


async def check_and_store(client, raw_input: str, *, force: bool = False) -> tuple[CheckTarget | None, str, dict | None, bool]:
    """Single manual check of a raw target. Resolves it to an identity, then - unless `force` - reuses
    a stored result still within the 24h TTL instead of re-probing (same skip as Check All). Returns
    (target, status, previous_entry, cached): cached=True means the fresh stored result was reused and
    no reachability probe ran. target is None only when the input can't form an identity."""
    from telethon.errors import FloodWaitError
    from collectors.resolve import NotAMemberError, invite_hash

    entity = None
    fail_status: str | None = None
    inv = invite_hash(raw_input)
    try:
        entity = await _resolve_probe(client, raw_input)
        # Preserve the invite link for a private group so the stored key matches the card's key.
        target = target_from_entity(entity, invite_link=raw_input if inv else None)
    except FloodWaitError:
        raise  # a rate-limit isn't a result - propagate so the caller can show the wait time
    except NotAMemberError:
        # A valid private invite we never joined: the group is alive (reachable) even if we can't
        # scrape it, so judge the invite itself instead of marking it ❌ private. A FloodWait here
        # propagates too (check_invite re-raises it), so the caller shows the wait.
        target = _target_from_raw(raw_input)
        fail_status = (await check_invite(client, inv))[0] if inv else STATUS_PRIVATE
    except Exception as e:
        target, fail_status = _target_from_raw(raw_input), classify_reachability(e)

    store = load_status()
    previous = store.get(target.canonical_key) if target is not None else None
    if not force and previous is not None and is_fresh(previous):
        return target, previous.get("status", STATUS_ERROR), previous, True

    # Same exists+access logic as Check All (Forbidden / restricted / deleted / read-probe).
    status = fail_status if fail_status is not None else await _status_from_entity(client, entity)
    if target is not None:
        store[target.canonical_key] = _entry(target, status, datetime.now(timezone.utc))
        save_status(store)
    return target, status, previous, False


# --- aggregated view + removal (shared by the bot views and the CLI) ----------------------------

@dataclass
class TargetStatus:
    target: CheckTarget
    entry: dict | None  # the stored status entry, or None if never checked

    @property
    def status(self) -> str | None:
        return (self.entry or {}).get("status")


async def build_view(pool) -> list[TargetStatus]:
    """Every checkable target joined with its stored status, favorites first then alphabetical.
    Stateless: re-read live so the drill-down callbacks always reflect the current store."""
    targets = sort_targets(await gather_targets(pool))
    store = load_status()
    return [TargetStatus(tgt, store.get(tgt.canonical_key)) for tgt in targets]


async def build_link_view(pool, *, exclude: set[str] | None = None) -> list[TargetStatus]:
    """Every archived link as a check target joined with its stored status, with the resolved kind
    (user/channel/group) filled in from the store so the Check Links summary and drill-downs split by
    kind exactly like Check All. A link never checked (or one that couldn't be resolved) keeps the
    placeholder GROUP kind until a probe learns better. exclude drops just-removed keys so they vanish
    before the watcher has pruned the DB."""
    store = load_status()
    view: list[TargetStatus] = []
    for tgt in await gather_link_targets(pool):
        if exclude and tgt.canonical_key in exclude:
            continue
        entry = store.get(tgt.canonical_key)
        kind = (entry or {}).get("kind") or tgt.kind
        view.append(TargetStatus(replace(tgt, kind=kind), entry))
    view.sort(key=lambda x: (x.target.title or "").lower())
    return view


async def remove_inactive(pool, kinds: set[str]) -> tuple[int, set[str]]:
    """Remove every confirmed-dead (❌) target of the given kinds from its CSVs (the watcher then
    prunes the DB) and from favorites, and forget its stored status. STATUS_ERROR (⚠️) is never
    touched. Returns (removed_count, removed_canonical_keys)."""
    from bot import favorites_store
    from collectors.csv_import import find_group_csv_files

    view = await build_view(pool)
    dead = [x for x in view if x.target.kind in kinds and is_dead(x.status)]

    store = load_status()
    removed: set[str] = set()
    for x in dead:
        tgt = x.target
        favorites_store.remove(tgt.username, tgt.tg_id, tgt.link)  # no-op if it isn't a favorite
        if tgt.kind in (GROUP, CHANNEL):
            for file in find_group_csv_files(tgt.canonical_key, tgt.title, which="all"):
                try:
                    file.unlink()
                except OSError:
                    pass
        store.pop(tgt.canonical_key, None)
        removed.add(tgt.canonical_key)
    save_status(store)
    return len(dead), removed


# --- link reachability (Check Links: probe every archived link's target) ------------------------

def link_status_key(link: str) -> str:
    """Status-store key for an archived link, namespaced so it never collides with a group/user key
    even when the link points to a scraped group. Keyed by link_key (message id/query already stripped)."""
    from db.queries.links import link_key
    return f"link:{link_key(link)}"


async def gather_link_targets(pool) -> list[CheckTarget]:
    """Every distinct archived link as a check target: probing the link = resolving the user/channel/
    group it points to. Deduped by link (the DB already holds only clean entity links). Blacklisted
    links are excluded by list_all_links."""
    from bot.group_links import link_display
    from db.queries.links import list_all_links

    by_key: dict[str, CheckTarget] = {}
    for r in await list_all_links(pool):
        key = link_status_key(r["link"])
        by_key.setdefault(key, CheckTarget(
            kind=GROUP,  # unknown until resolved; kind only groups the Check All summary, unused here
            canonical_key=key,
            title=link_display(r["link"]),
            link=r["link"],
            resolve_input=r["link"],
        ))
    return list(by_key.values())


async def remove_inactive_links(pool, kinds: set[str] | None = None) -> tuple[int, int, set[str]]:
    """Remove every confirmed-dead (❌) archived link from the links CSVs (the watcher then prunes the
    DB) and forget its stored status. With `kinds`, only dead links whose resolved kind is in that set
    are removed (per-kind removal from the Check Links drill-down); None removes all dead links. ⚠️
    transient failures are never touched. Returns (dead_links, csv_rows_removed, removed_keys)."""
    from collectors.csv_import import remove_links_from_csvs
    from db.queries.links import link_key

    store = load_status()
    dead_keys: set[str] = set()
    forget: set[str] = set()
    for x in await build_link_view(pool):
        if kinds is not None and x.target.kind not in kinds:
            continue
        if is_dead(x.status):
            dead_keys.add(link_key(x.target.link))
            forget.add(x.target.canonical_key)

    rows_removed = remove_links_from_csvs(dead_keys) if dead_keys else 0
    for k in forget:
        store.pop(k, None)
    save_status(store)
    return len(forget), rows_removed, forget
