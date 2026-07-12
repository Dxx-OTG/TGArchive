import os
from pathlib import Path

import asyncpg
from watchfiles import awatch

from bot.log import log
from collectors.csv_import import (
    FOLDERS,
    LINK_FOLDER,
    REGISTERED_FOLDER,
    REGISTERED_MEMBERS_FOLDER,
    import_all,
    import_links,
    import_registered,
    import_registered_members,
    reconcile_with_csv,
)
from db.queries.groups import merge_duplicate_groups

WATCH_PATHS = ([str(folder) for folder, _source in FOLDERS]
               + [str(LINK_FOLDER), str(REGISTERED_FOLDER), str(REGISTERED_MEMBERS_FOLDER)])


async def _sync(pool: asyncpg.Pool, collector_pool: asyncpg.Pool | None, *, full: bool = False) -> None:
    """One import+merge+prune pass: import new/changed CSVs (members and links), merge duplicate
    groups, prune rows no longer backed by any CSV. Merge/prune need DATABASE_URL_COLLECTOR (app_bot
    can't DELETE).

    full=True re-imports EVERY CSV regardless of the mtime cache (output/.import_manifest.json). The
    startup pass uses it so the DB always mirrors the CSVs even when the cache is stale relative to the
    DB - e.g. after a transfer (CSVs + cache copied onto a fresh DB) or a manual DB reset. The
    watch loop then uses the cache (full=False) so live edits don't re-read unchanged files. Import is
    idempotent (ON CONFLICT DO NOTHING), so a full pass on an already-synced DB is a cheap no-op."""
    only_new = not full
    try:
        lines = await import_all(pool, only_new=only_new)
        for line in lines:
            log(f"📥 CSV Watcher: {line}")

        link_lines = await import_links(pool, only_new=only_new)
        for line in link_lines:
            log(f"🔗 CSV Watcher: {line}")

        reg_lines = await import_registered(pool, only_new=only_new)
        for line in reg_lines:
            log(f"📌 CSV Watcher: {line}")

        regm_lines = await import_registered_members(pool, only_new=only_new)
        for line in regm_lines:
            log(f"📌 CSV Watcher: {line}")

        if collector_pool is not None:
            merged = await merge_duplicate_groups(collector_pool)
            if merged:
                log(f"🔗 CSV Watcher: merged {merged} duplicate groups")

            result = await reconcile_with_csv(collector_pool)
            if any(result.values()):
                log(f"🧹 CSV Watcher: pruned -> {result}")
    except Exception as e:
        log(f"⚠️ CSV Watcher: import error: {e}")


async def watch_loop(pool: asyncpg.Pool) -> None:
    """Reacts to filesystem changes in output/Members From Groups and output/Members From Messages
    instead of polling on a timer: any CSV created/edited/deleted triggers a sync pass right away, so
    the database mirrors the CSVs continuously. Started by bot/main.py."""
    collector_pool: asyncpg.Pool | None = None
    collector_dsn = os.environ.get("DATABASE_URL_COLLECTOR")
    if collector_dsn:
        try:
            collector_pool = await asyncpg.create_pool(collector_dsn, min_size=1, max_size=2)
        except Exception as e:
            log(f"⚠️ CSV Watcher: cannot connect as collector, pruning disabled: {e}")

    for path in WATCH_PATHS:
        Path(path).mkdir(parents=True, exist_ok=True)

    try:
        # Startup: a FULL import so the DB mirrors the CSVs even if the mtime cache is stale relative
        # to the DB (fresh DB after a transfer, a manual reset, …). Then watch incrementally.
        await _sync(pool, collector_pool, full=True)

        async for _changes in awatch(*WATCH_PATHS):
            await _sync(pool, collector_pool)
    finally:
        if collector_pool is not None:
            await collector_pool.close()
