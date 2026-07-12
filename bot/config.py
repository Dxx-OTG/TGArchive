import os
import sys

from dotenv import load_dotenv

load_dotenv()


def _parse_admins(raw: str | None) -> tuple[set[int], set[str]]:
    """ADMIN_USER_IDS accepts both numeric Telegram IDs and usernames (with or without @),
    mixed and comma-separated. Returns (numeric_ids, normalized_usernames)."""
    ids: set[int] = set()
    usernames: set[str] = set()
    if not raw:
        return ids, usernames
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if token.isdigit():
            ids.add(int(token))
        else:
            usernames.add(token.lstrip("@").lower())
    return ids, usernames


BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
DATABASE_URL = os.environ.get("DATABASE_URL_BOT", "")
ADMIN_USER_IDS, ADMIN_USERNAMES = _parse_admins(os.environ.get("ADMIN_USER_IDS"))


def require_complete() -> None:
    """Print an actionable message and exit if BOT_TOKEN/DATABASE_URL_BOT are missing, instead of a
    deep aiogram/asyncpg traceback. Called by bot/main.py before startup."""
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not DATABASE_URL:
        missing.append("DATABASE_URL_BOT")

    if missing:
        print("=" * 60)
        print("❌ Cannot start: missing or empty in .env: " + ", ".join(missing))
        if "DATABASE_URL_BOT" in missing:
            print("   Run setup_database.bat first (it writes this).")
        if "BOT_TOKEN" in missing:
            print("   Get one from @BotFather. Use TGArchive.bat - it checks .env for you.")
        print("   See README -> '.env configuration'.")
        print("=" * 60)
        sys.exit(1)

    if not ADMIN_USER_IDS and not ADMIN_USERNAMES:
        print("ℹ️  ADMIN_USER_IDS is empty: every command is rejected. Send /start, read your")
        print("   tg_user_id from this console, add it to .env, restart. (README -> '.env configuration')")
