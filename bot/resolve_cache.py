"""24h resolve cache for live-resolved identities of entities that are NOT in the archive or
favorites, so reopening the same pasted/tapped link doesn't re-hit Telegram every time.

Why: browsing the links captured in a group opens one card per link. Opening a link you HAVEN'T saved
would otherwise resolve it live each time (one ResolveUsername/CheckChatInvite call - the calls
Telegram rate-limits hardest). This caches the resolved identity so reopening the same link is free,
without ever adding it to the database.

Kept in RAM for speed and mirrored to output/.resolve_cache.json so it survives a bot/CLI restart -
you pick up where you left off instead of re-resolving everything after a restart. Entries expire 24h
after they're cached (wall-clock time, so the TTL survives a restart) and the store self-prunes on
write (and caps its size), so it clears itself over a day and never grows without bound. Wipe it from
the menu's Clean Logs/History (which deletes the file) -> the next start is clean.
"""
import json
import time
from dataclasses import asdict
from pathlib import Path

_TTL_SECONDS = 24 * 3600
_MAX_ENTRIES = 5000
CACHE_FILE = Path("output") / ".resolve_cache.json"

_cache: "dict[str, tuple[float, object]]" = {}  # key -> (epoch time cached, ResolvedTarget | NEGATIVE)
_loaded = False

# Sentinel cached for a reference that genuinely doesn't exist (a freed @username, a revoked/expired
# invite) so reopening a dead link is free too. Never cached for transient errors (FloodWait/network).
NEGATIVE = object()


def _ensure_loaded() -> None:
    """Populate the RAM cache from the on-disk file, once, dropping already-expired entries. A missing
    or unreadable file just leaves an empty cache (the old in-memory behaviour)."""
    global _loaded
    if _loaded:
        return
    _loaded = True  # set first: a failed/absent load still counts as "loaded" (empty cache)
    try:
        raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        from bot.favorites import ResolvedTarget  # lazy: avoids an import cycle at module load
    except (OSError, ValueError, ImportError):
        return
    now = time.time()
    for key, e in (raw.get("entries") or {}).items():
        at = e.get("at", 0)
        if now - at > _TTL_SECONDS:
            continue
        if e.get("neg"):
            _cache[key] = (at, NEGATIVE)
        else:
            try:
                _cache[key] = (at, ResolvedTarget(**(e.get("target") or {})))
            except TypeError:
                continue  # the stored shape changed -> drop this stale entry


def _save() -> None:
    entries = {}
    for key, (at, value) in _cache.items():
        if value is NEGATIVE:
            entries[key] = {"at": at, "neg": True}
        else:
            entries[key] = {"at": at, "target": asdict(value)}
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_FILE.with_suffix(".json.new")
        tmp.write_text(json.dumps({"version": 1, "entries": entries}), encoding="utf-8")
        tmp.replace(CACHE_FILE)
    except OSError:
        pass  # a cache that can't be written just behaves like a plain in-memory one


def get(key: str):
    """The cached identity for `key` while still within its 24h TTL, else None (dropping a stale one)."""
    _ensure_loaded()
    entry = _cache.get(key)
    if entry is None:
        return None
    cached_at, value = entry
    if time.time() - cached_at > _TTL_SECONDS:
        _cache.pop(key, None)  # a stale-on-read entry: next put() prunes + rewrites the file
        return None
    return value


def put(key: str, value) -> None:
    """Cache a freshly resolved identity (or NEGATIVE), pruning expired/overflow entries first, then
    persist the whole cache so it survives a restart."""
    _ensure_loaded()
    _prune()
    _cache[key] = (time.time(), value)
    _save()


def clear() -> None:
    """Drop everything, in RAM and on disk."""
    _cache.clear()
    try:
        CACHE_FILE.unlink()
    except OSError:
        pass


def _prune() -> None:
    now = time.time()
    for k in [k for k, (cached_at, _) in _cache.items() if now - cached_at > _TTL_SECONDS]:
        _cache.pop(k, None)
    if len(_cache) > _MAX_ENTRIES:
        for k in sorted(_cache, key=lambda k: _cache[k][0])[: len(_cache) - _MAX_ENTRIES]:
            _cache.pop(k, None)
