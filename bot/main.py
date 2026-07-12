import asyncio
import signal

import asyncpg
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot import botinfo
from bot.commands_menu import setup_commands
from bot.config import BOT_TOKEN, DATABASE_URL, require_complete
from bot.csv_watcher import watch_loop
from bot.loader import discover_routers
from bot.middlewares.admin_only import AdminOnlyMiddleware
from bot.middlewares.rate_limit import RateLimitMiddleware
from bot.telethon_client import close_scrape_client, init_scrape_client
from db.pool import close_pool, init_pool


def _print_db_error(message: str) -> None:
    print("=" * 60)
    print(f"❌ {message}")
    print("   Run Setup Database from TGArchive.bat to repair or reset it. (README -> 'Troubleshooting')")
    print("=" * 60)


async def main() -> None:
    try:
        pool = await init_pool(DATABASE_URL)
        # Schema sanity check: a wrong password already fails inside init_pool() above.
        await pool.fetchval("SELECT 1 FROM groups LIMIT 1")
    except asyncpg.InvalidAuthorizationSpecificationError as e:
        _print_db_error(f"Database credentials don't work: {e}")
        await close_pool()
        return
    except (asyncpg.UndefinedTableError, asyncpg.InvalidCatalogNameError) as e:
        _print_db_error(f"Database schema missing or broken: {e}")
        await close_pool()
        return
    except Exception as e:
        _print_db_error(f"Cannot reach the database: {e}")
        await close_pool()
        return

    await init_scrape_client()

    watcher_task = asyncio.create_task(watch_loop(pool))

    # link_preview_is_disabled: the group/member/search listings are full of t.me links; without
    # this every message would sprout a preview card for the first one.
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True))
    me = await bot.get_me()
    botinfo.set_bot_username(me.username)  # needed for the t.me deep links in the hub's group lists
    await setup_commands(bot)
    dp = Dispatcher()

    # Outer middlewares run on every message and button click, in registration order. rate_limit
    # goes first so even a non-admin flood is capped (without it, every stranger message would get
    # its own reply and could trip the bot's own send limits); then admin_only rejects non-admins.
    # (Actions are recorded in the file log, log/ - there's no DB audit table anymore.)
    rate_limit = RateLimitMiddleware()
    admin_only = AdminOnlyMiddleware()
    dp.message.outer_middleware(rate_limit)
    dp.message.outer_middleware(admin_only)
    dp.callback_query.outer_middleware(rate_limit)
    dp.callback_query.outer_middleware(admin_only)

    routers = discover_routers()
    for router in routers:
        dp.include_router(router)
    print(f"🧩 Modules loaded: {[r.name for r in routers]}")

    # Windows asyncio lacks add_signal_handler, so wire SIGINT to stop_polling() for a clean CTRL+C.
    loop = asyncio.get_running_loop()
    signal.signal(signal.SIGINT, lambda *_: loop.create_task(dp.stop_polling()))

    try:
        print("🤖 TGArchive started, listening...")
        await dp.start_polling(bot)
    finally:
        watcher_task.cancel()
        await close_scrape_client()
        await close_pool()
        await bot.session.close()
        print("🛑 TGArchive stopped.")


if __name__ == "__main__":
    require_complete()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
