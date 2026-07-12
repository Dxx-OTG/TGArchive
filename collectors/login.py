"""Interactive Telegram login for the scraping account, runnable straight from the main menu
(TGArchive.bat) without opening the CLI. It authenticates the Telethon session (phone number + OTP,
plus 2FA password if enabled) and — when an account is already logged in — offers to SWITCH accounts:
it logs the old one out, deletes its .session file, and logs the new one in.

Run as `python -m collectors.login` from the repo root (scripts/tg_login.bat does this inside the
venv). It holds the shared Telethon lock so it can't run while the bot or the CLI is connected — they
all share one .session file.
"""
import asyncio
import os
from pathlib import Path

from collectors.telethon_client import create_client
from collectors.telethon_lock import TelethonSessionBusy, acquire_telethon_lock, release_telethon_lock

ROOT = Path(__file__).resolve().parent.parent


def _session_files() -> list[Path]:
    """The on-disk files a Telethon SqliteSession keeps for TG_SESSION_NAME — the account lives here,
    so switching account means deleting these."""
    name = os.environ.get("TG_SESSION_NAME") or "telegram_session"
    return [ROOT / f"{name}.session", ROOT / f"{name}.session-journal"]


def _delete_session_files() -> None:
    for f in _session_files():
        try:
            f.unlink()
        except FileNotFoundError:
            pass
        except OSError as e:
            print(f"⚠️  Could not delete {f.name}: {e}")


def _who(me) -> str:
    handle = f"@{me.username}" if getattr(me, "username", None) else "(no username)"
    name = (getattr(me, "first_name", "") or "").strip()
    return f"{name} {handle} · id {me.id}".strip()


async def _safe_disconnect(client) -> None:
    try:
        if client.is_connected():
            await client.disconnect()
    except Exception:
        pass


async def _login(client) -> bool:
    """Interactive phone + OTP (+ 2FA) login. Returns True on success."""
    try:
        await client.start()  # prompts for phone, the login code, and the 2FA password as needed
    except Exception as e:
        print(f"❌ Login failed: {e}")
        return False
    me = await client.get_me()
    print(f"\n✅ Logged in as {_who(me)}.")
    return True


async def _handle_switch(client) -> None:
    me = await client.get_me()
    print(f"✅ Already logged in as {_who(me)}.\n")
    print("  [1] Switch account  (log out this one, delete its session, log in another)")
    print("  [0] Keep this account and go back")
    if input("\n📌 Choice: ").strip() != "1":
        print("👍 Keeping the current account.")
        return

    print("\n🔄 Logging out the current account…")
    try:
        await client.log_out()  # revokes the session server-side and removes the local file
    except Exception as e:
        print(f"⚠️  Server logout didn't complete ({e}); removing the local session anyway.")
    await _safe_disconnect(client)
    _delete_session_files()  # make sure the old .session is gone before the new login writes a fresh one
    print("🧹 Old session removed.\n")
    print("Now log in with the NEW account (phone number + code, plus 2FA password if enabled).\n")

    new_client = create_client()
    try:
        await new_client.connect()
        await _login(new_client)
    finally:
        await _safe_disconnect(new_client)


async def _handle_first_login(client) -> None:
    print("ℹ️  No account is logged in yet.")
    print("    You'll enter your phone number and the code Telegram sends you (plus your 2FA")
    print("    password if you set one). It's saved to the .session file, so you only do this once.\n")
    if input("Log in now? [y/N]: ").strip().lower() != "y":
        print("Cancelled — nothing changed.")
        return
    await _login(client)


async def main() -> None:
    os.chdir(ROOT)  # the .session and lock files are relative paths — run from the repo root
    print("=" * 60)
    print("🔑  TGArchive | Telegram login (scraping account)")
    print("=" * 60)

    try:
        client = create_client()
    except RuntimeError as e:
        print(f"❌ {e}")
        print("   Fill in TG_API_ID / TG_API_HASH / TG_SESSION_NAME in .env (see README), then retry.")
        return

    try:
        acquire_telethon_lock()
    except TelethonSessionBusy as e:
        print(f"❌ {e}")
        return

    try:
        await client.connect()
        if await client.is_user_authorized():
            await _handle_switch(client)
        else:
            await _handle_first_login(client)
    finally:
        await _safe_disconnect(client)
        release_telethon_lock()
        print("=" * 60)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n🛑 Cancelled.")
