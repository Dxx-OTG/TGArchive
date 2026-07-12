"""TGArchive CLI — a terminal front-end that mirrors the Telegram bot.

Same commands, same PostgreSQL, same logic as the bot (see CLI/commands.py). On startup it acquires
the shared Telethon lock (so it can never run at the same time as the bot - they'd both write the
DB), connects the database, and syncs the CSVs into it (like the bot's watcher) so searches see the
current data. Reads work without a Telegram login; scraping and classifying a favorite prompt for a
one-time login when first used.
"""
import asyncio
import os
import sys
from pathlib import Path

# Run from the repo root so Path("output")/... and package imports resolve regardless of launch dir.
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import asyncpg

from bot.csv_watcher import _sync
from collectors.telethon_client import create_client
from collectors.telethon_lock import TelethonSessionBusy, acquire_telethon_lock, release_telethon_lock

from CLI import commands as c

# command -> handler(ctx, arg). Mirrors the bot's command set; members/links stand in for the bot's
# tappable 👥/🔗 counts (a terminal has no inline buttons).
HANDLERS = {
    "scrapemembers": c.cmd_scrapemembers,
    "scrapemessages": c.cmd_scrapemessages,
    "scrapelinks": c.cmd_scrapelinks,
    "searchusers": c.cmd_searchusers,
    "searchbots": c.cmd_searchbots,
    "searchgroups": c.cmd_searchgroups,
    "searchchannels": c.cmd_searchchannels,
    "searchlinks": c.cmd_searchlinks,
    "groups": c.cmd_groups,
    "channels": c.cmd_channels,
    "users": c.cmd_users,
    "bots": c.cmd_bots,
    "members": c.cmd_members,
    "links": c.cmd_links,
    "favorites": c.cmd_favorites,
    "check": c.cmd_check,
    "card": c.cmd_card,
    "stats": c.cmd_stats,
    "export": c.cmd_export,
    "delete": c.cmd_delete,
}

HELP = """\
Commands (same as the Telegram bot):

  🤖 Scrape
    scrapemembers <group>                 member list of a group/supergroup
    scrapemessages <group> [limit]        senders of recent messages (default 500, max 5000)
    scrapelinks <group|channel> [limit]   shared t.me links

  🔎 Search
    searchusers <text|@user|id>           find a person
    searchbots <text|@bot|id>             find a bot
    searchgroups <text|@name|link>        find a group/supergroup
    searchchannels <text|@name|link>      find a broadcast channel
    searchlinks <text>                    find a shared t.me link by its URL

  🗂 Browse
    groups                                all scraped groups
    channels                              all scraped channels
    users                                 all users (with group/link counts)
    bots                                  all bots (with group/link counts)
    members <@username|link>              members of one group
    links <@username|link>                links of one group/channel

  ⭐ Favorites
    favorites                             list saved favorites
    favorites <user|group|channel>        save one (resolved on Telegram)
    favorites remove <…>                  drop one

  🔎 Check
    check <@username|link|id> [force]     is this group/channel/user still reachable? (24h cache; force re-checks)
    check all [force]                     check every scraped + favorite entity (24h cache; force re-checks)
    check prune                           remove the inactive (❌) entities from CSVs and favorites
    check links [force]                   check every archived link's target (24h cache; force re-checks)
    check links prune                     remove the inactive (❌) links from the link CSVs

  🪪 Card
    card <@username|link|id>              open an action menu for an entity (or just paste one)

  📊 Data
    stats                                 database totals
    stats <element>                       list them all — element: groups | channels | users | bots
                                          | withusername | nousername | links
    export <username> | export all        export CSVs (one entity, or the whole archive as a zip)
    delete <username> | delete all        delete CSVs (one entity, or the whole archive)

    help                                  this guide
    exit                                  quit
"""


class Ctx:
    """Shared handles passed to every command handler."""

    def __init__(self, client, bot_pool, collector_pool, authorized):
        self.client = client
        self.bot_pool = bot_pool
        self.collector_pool = collector_pool
        self.authorized = authorized

    async def get_client(self):
        """For favorites: raise (→ local fallback) when not logged in, like the bot does."""
        if not self.authorized:
            raise RuntimeError("Telethon session not authorized yet - log in first (used by scraping).")
        return self.client

    async def ensure_client(self):
        """For scraping: offer a one-time interactive login when not authorized yet."""
        if self.authorized:
            return self.client
        print("Telegram login required for scraping (phone number + OTP, plus 2FA if enabled).")
        if input("Log in now? [y/N]: ").strip().lower() != "y":
            return None
        try:
            await self.client.start()
        except Exception as e:
            print(f"❌ Login failed: {e}")
            return None
        self.authorized = True
        return self.client

    async def resync(self):
        await _sync(self.bot_pool, self.collector_pool)


async def _open_bot_pool() -> asyncpg.Pool | None:
    dsn = os.environ.get("DATABASE_URL_BOT")
    if not dsn:
        print("❌ DATABASE_URL_BOT is missing in .env. Run Setup Database from TGArchive.bat first.")
        return None
    try:
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
        await pool.fetchval("SELECT 1 FROM groups LIMIT 1")  # same schema sanity check as the bot
        return pool
    except (asyncpg.UndefinedTableError, asyncpg.InvalidCatalogNameError):
        print("❌ Database schema missing or broken. Run Setup Database from TGArchive.bat.")
    except asyncpg.InvalidAuthorizationSpecificationError:
        print("❌ Database credentials don't work. Run Setup Database from TGArchive.bat.")
    except Exception as e:
        print(f"❌ Cannot reach the database: {e}")
    return None


async def _dispatch(ctx: Ctx, line: str) -> bool:
    """Run one command line. Returns False to exit the REPL."""
    cmd, _, arg = line.strip().partition(" ")
    cmd = cmd.lower()
    arg = arg.strip()
    if cmd in ("exit", "quit", "q"):
        return False
    if cmd in ("help", "?", ""):
        print(HELP)
        return True
    handler = HANDLERS.get(cmd)
    if handler is None:
        # A pasted @username / t.me link / id opens its card, like the bot.
        from bot.card import parse_entity_ref
        if parse_entity_ref(line.strip()):
            await c.cmd_card(ctx, line.strip())
            return True
        print(f"❓ Unknown command '{cmd}'. Type help.")
        return True
    try:
        await handler(ctx, arg)
    except Exception as e:
        print(f"❌ Error: {e}")
    return True


async def main() -> None:
    print("=" * 60)
    print("🗄️  TGArchive CLI")
    print("=" * 60)

    try:
        client = create_client()
    except RuntimeError as e:
        print(f"❌ {e}")
        print("   Fill in TG_API_ID/TG_API_HASH in .env (see README), then try again.")
        return

    try:
        acquire_telethon_lock()
    except TelethonSessionBusy as e:
        print(f"❌ {e}")
        return

    bot_pool = None
    collector_pool = None
    try:
        await client.connect()
        authorized = await client.is_user_authorized()
        if authorized:
            me = await client.get_me()
            print(f"✅ Telegram: logged in as {me.first_name or ''} @{me.username or '(no username)'}")
        else:
            print("ℹ️  Telegram: not logged in — reads work; scraping will ask you to log in when first used.")

        bot_pool = await _open_bot_pool()
        if bot_pool is None:
            return
        collector_dsn = os.environ.get("DATABASE_URL_COLLECTOR")
        if collector_dsn:
            try:
                collector_pool = await asyncpg.create_pool(collector_dsn, min_size=1, max_size=2)
            except Exception as e:
                print(f"⚠️  Collector role unavailable, pruning/merge disabled this session: {e}")

        print("🔄 Syncing CSVs into the database…")
        await _sync(bot_pool, collector_pool, full=True)  # full import on startup (mirrors the bot)

        ctx = Ctx(client, bot_pool, collector_pool, authorized)
        print("\nType a command, or 'help'. 'exit' to quit.\n")

        while True:
            try:
                line = input("tgarchive> ")
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not await _dispatch(ctx, line):
                break
    finally:
        await client.disconnect()
        release_telethon_lock()
        if bot_pool is not None:
            await bot_pool.close()
        if collector_pool is not None:
            await collector_pool.close()
        print("🛑 CLI stopped.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 CTRL + C → exit")
