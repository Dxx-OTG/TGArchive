import os
import shutil
import signal
import socket
import subprocess
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).parent.parent
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE_PATH = ROOT / ".env.example"
SCRIPTS_DIR = Path(__file__).parent

# Needed to run the bot or the scraping tools at all.
REQUIRED_KEYS = ["BOT_TOKEN", "TG_API_ID", "TG_API_HASH"]


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def _read_env(path: Path) -> dict[str, str]:
    """Minimal .env reader (KEY=VALUE per line) so this menu needs no third-party packages and runs
    on the system Python - that way it never holds .venv open and Prepare Transfer can delete it."""
    values: dict[str, str] = {}
    try:
        # utf-8-sig strips a leading BOM, which Windows PowerShell's Out-File -Encoding utf8 adds.
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


def _db_reachable(url: str, timeout: float = 4.0) -> bool:
    """Quick TCP check that the Postgres host:port in the DSN is accepting connections: tells 'server
    up' from 'server down/unreachable'. It doesn't validate the credentials."""
    if not url:
        return False
    parsed = urlparse(url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 5432
    try:
        with socket.create_connection((host, port), timeout):
            return True
    except OSError:
        return False


def _find_psql() -> str | None:
    """Locate psql.exe: PATH first, then the default PostgreSQL install path."""
    found = shutil.which("psql")
    if found:
        return found
    candidates = sorted(Path(r"C:\Program Files\PostgreSQL").glob("*/bin/psql.exe"), reverse=True)
    return str(candidates[0]) if candidates else None


def _psql_query_ok(psql_exe: str, dsn: str, query: str, timeout: float = 5.0) -> bool:
    try:
        result = subprocess.run([psql_exe, dsn, "-tAc", query], capture_output=True, timeout=timeout)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _db_health(url: str) -> str:
    """Classifies the DB beyond plain TCP reachability: 'unreachable' | 'auth_failed' |
    'schema_broken' | 'ok' | 'unknown' (psql.exe not found - treat like 'ok'). It uses two psql probes
    instead of matching Postgres's error text."""
    if not _db_reachable(url):
        return "unreachable"

    psql_exe = _find_psql()
    if not psql_exe:
        return "unknown"

    if not _psql_query_ok(psql_exe, url, "SELECT 1"):
        return "auth_failed"

    if not _psql_query_ok(psql_exe, url, "SELECT 1 FROM groups LIMIT 1"):
        return "schema_broken"

    return "ok"


def _telethon_session_exists(values: dict[str, str]) -> bool:
    session_name = values.get("TG_SESSION_NAME") or "telegram_session"
    return (ROOT / f"{session_name}.session").exists()


def system_status() -> dict:
    """Single source of truth for what state the install is in. The bot can only run when stage
    == 'ready'; scraping needs the TG_* keys but not the database."""
    if not ENV_PATH.exists():
        return {"stage": "no_env"}

    values = _read_env(ENV_PATH)
    missing = [k for k in REQUIRED_KEYS if not values.get(k)]
    admin_empty = not values.get("ADMIN_USER_IDS")
    telethon_missing = not _telethon_session_exists(values)

    if missing:
        return {"stage": "env_incomplete", "missing": missing, "admin_empty": admin_empty}

    bot_url = values.get("DATABASE_URL_BOT") or ""
    if not bot_url:
        return {"stage": "db_unconfigured", "admin_empty": admin_empty, "telethon_missing": telethon_missing}

    health = _db_health(bot_url)
    if health == "unreachable":
        return {"stage": "db_unreachable", "admin_empty": admin_empty, "telethon_missing": telethon_missing}
    if health == "auth_failed":
        return {"stage": "db_auth_failed", "admin_empty": admin_empty, "telethon_missing": telethon_missing}
    if health == "schema_broken":
        return {"stage": "db_schema_broken", "admin_empty": admin_empty, "telethon_missing": telethon_missing}

    return {"stage": "ready", "admin_empty": admin_empty, "telethon_missing": telethon_missing}


def create_env_from_template() -> None:
    ENV_PATH.write_text(ENV_EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"✅ Created {ENV_PATH.name} from {ENV_EXAMPLE_PATH.name}.")


def _launch_editor(path: Path) -> bool:
    """Try to open `path` in a text editor, returning True if one was launched. Notepad may be
    missing (removed on Windows 11, or its App Execution Alias turned off) or replaced by a different
    version, so we try classic notepad in the PATH, then its absolute locations, then WordPad, then
    the OS default app. Returns False only if nothing could be launched at all."""
    for exe in ("notepad.exe",
                r"C:\Windows\System32\notepad.exe",
                r"C:\Windows\notepad.exe",
                "write.exe"):  # WordPad, as a last executable fallback
        try:
            subprocess.run([exe, str(path)])
            return True
        except (FileNotFoundError, OSError):
            continue
    try:
        os.startfile(str(path))  # whatever app is associated; may be absent for a ".env"
        return True
    except OSError:
        return False


def open_in_editor(path: Path) -> None:
    print(f"\n📝 Opening {path.name} in a text editor - fill it in and save it.")
    launched = _launch_editor(path)
    if not launched:
        # Nothing could be launched - show the path so the user can edit it by hand instead of the
        # menu crashing on a missing editor.
        print("\n⚠️  Couldn't open a text editor automatically.")
        print(f"    Open this file in any editor, fill it in, and save it:\n    {path}")
    # Always wait: some editors (the Windows 11 Store Notepad, the default-app launch) return
    # immediately instead of blocking until closed, so without this the menu would re-read .env
    # before you finished editing.
    try:
        input("\n📌 Press ENTER when you've saved and closed the editor...")
    except KeyboardInterrupt:
        pass


def find_program(name: str) -> Path | None:
    candidate = SCRIPTS_DIR / name
    return candidate if candidate.exists() else None


def print_header():
    print("=" * 60)
    print("🗄️  TGArchive | Main Menu")
    print("=" * 60)


def run_inline(program: Path) -> None:
    """Run a .bat in this same window and wait for it (setup/transfer/clean/scraping). Clears
    first so the tool's output starts on a clean screen, then keeps it until ENTER."""
    clear()
    print(f"\n🚀 Launch {program.name}")
    original_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        subprocess.run([str(program)], shell=True)
    finally:
        signal.signal(signal.SIGINT, original_sigint)
    print(f"✅ {program.name} done | back to menu")
    try:
        input("\n📌 Press ENTER to continue...")
    except KeyboardInterrupt:
        pass


def run_new_window(program: Path) -> None:
    """Run a long-lived .bat in its own window so the menu stays usable (used for the bot)."""
    print(f"\n🚀 Launch {program.name} in a new window")
    subprocess.Popen(f'start "TGArchive - {program.stem}" "{program.resolve()}"', shell=True)
    print("✅ Started in a separate window: the menu stays free. To stop it, close that window.")
    try:
        input("\n📌 Press ENTER to continue...")
    except KeyboardInterrupt:
        pass


def run_setup_database() -> None:
    setup = find_program("setup_database.bat")
    if setup is None:
        print("❌ setup_database.bat not found in scripts/.")
        input("\n📌 Press ENTER to continue...")
        return
    run_inline(setup)


def run_cli() -> None:
    sm = find_program("start_menu.bat")
    if sm is None:
        print("❌ start_menu.bat not found in scripts/.")
        input("\n📌 Press ENTER to continue...")
        return
    run_inline(sm)


def run_tg_login() -> None:
    login = find_program("tg_login.bat")
    if login is None:
        print("❌ tg_login.bat not found in scripts/.")
        input("\n📌 Press ENTER to continue...")
        return
    run_inline(login)


# ---- Guided steps shown until everything is ready ---------------------------------------------

def step_no_env() -> bool:
    print_header()
    print("⚠️  No .env file found yet (first run).")
    if not ENV_EXAMPLE_PATH.exists():
        print(f"    {ENV_EXAMPLE_PATH.name} is missing too - your copy is incomplete, re-clone the project.")
        input("\n📌 Press ENTER to exit...")
        return False
    print()
    print("  [1] Create .env from the template and open it to fill in your values")
    print("  [0] Exit")
    choice = input("\n📌 Choice: ").strip()
    if choice == "1":
        create_env_from_template()
        open_in_editor(ENV_PATH)
        return True
    return False


def step_env_incomplete(status: dict) -> bool:
    print_header()
    print("⚠️  .env is missing some required values:")
    for key in status["missing"]:
        print(f"    - {key}")
    print()
    print("  [1] Open .env in a text editor to fill them in")
    print("  [0] Exit")
    choice = input("\n📌 Choice: ").strip()
    if choice == "1":
        open_in_editor(ENV_PATH)
        return True
    return False


def step_db_not_ready(status: dict) -> bool:
    print_header()
    stage = status["stage"]
    if stage == "db_auth_failed":
        print("⚠️  Database reachable, but the credentials in .env don't work (wrong/stale password).")
        print("    This usually happens after Setup Database was run from a different copy of this")
        print("    project folder. Setup Database can recover access without reinstalling PostgreSQL.")
    elif stage == "db_schema_broken":
        print("⚠️  Database reachable and credentials work, but the expected tables are missing or")
        print("    broken (incomplete/corrupted schema). Setup Database can reapply it.")
    elif stage == "db_unreachable":
        print("⚠️  Database configured but unreachable (PostgreSQL stopped, deleted, or unknown error).")
        print("    Setup Database can repair or reset it (no PostgreSQL reinstall unless unavoidable).")
    else:
        print("⚠️  Database not set up yet. Setup Database installs PostgreSQL if needed and creates it.")
    print()
    print("  [1] Setup / Repair Database  (recommended)")
    print("  [2] Open .env in a text editor")
    print("  [0] Exit")
    print("  (The CLI needs the database too, so set it up first.)")
    choice = input("\n📌 Choice: ").strip()
    if choice == "1":
        run_setup_database()
        return True
    if choice == "2":
        open_in_editor(ENV_PATH)
        return True
    return False


# ---- Full menu (only when ready) -------------------------------------------------------------

def full_menu(status: dict) -> bool:
    """Returns False to exit the program, True to loop."""
    print_header()
    if status["admin_empty"]:
        print("ℹ️  ADMIN_USER_IDS is empty - the bot rejects everyone. Start it, send /start, read your")
        print("   tg_user_id from the bot window, add it via [5], restart. See README -> '.env configuration'.")
        print()

    if status["telethon_missing"]:
        print("ℹ️  Telegram scraping account not authenticated yet - use [3] 🔑 Telegram Login to")
        print("   sign in (phone + OTP). Until then, scraping from the bot/CLI is unavailable.")
        print()

    # Same option, label reflects the current state: authenticate when logged out, switch when in.
    tg_login_label = (
        "🔑 Telegram Login  (authenticate the scraping account)"
        if status["telethon_missing"]
        else "🔁 Switch Telegram Account  (log out, then log in another)"
    )

    print("  [1] 🤖 Start The Bot")
    print("  [2] 🛠️  CLI (mirror of the bot in the terminal)")
    print(f"  [3] {tg_login_label}")
    print("  [4] 🧹 Clean Logs/History")
    print("  [5] 📦 Prepare Transfer To New PC")
    print("  [6] ⚙️  Open .env in a text editor")
    print("  [0] Exit")
    print("=" * 60)

    choice = input("\n📌 Choice: ").strip()

    if choice == "1":
        bot = find_program("start_bot.bat")
        if bot:
            run_new_window(bot)
        return True
    if choice == "2":
        run_cli()
        return True
    if choice == "3":
        run_tg_login()
        return True
    if choice == "4":
        clean = find_program("clean_logs.bat")
        if clean:
            run_inline(clean)
        return True
    if choice == "5":
        transfer = find_program("prepare_transfer.bat")
        if transfer:
            run_inline(transfer)
        return True
    if choice == "6":
        open_in_editor(ENV_PATH)
        return True
    if choice == "0":
        return False

    print("⚠️ Invalid choice, try again")
    input("\n📌 Press ENTER to continue...")
    return True


def main():
    try:
        while True:
            clear()
            status = system_status()
            stage = status["stage"]

            if stage == "no_env":
                keep_going = step_no_env()
            elif stage == "env_incomplete":
                keep_going = step_env_incomplete(status)
            elif stage in ("db_unconfigured", "db_unreachable", "db_auth_failed", "db_schema_broken"):
                keep_going = step_db_not_ready(status)
            else:
                keep_going = full_menu(status)

            if not keep_going:
                print("\n🛑 Exit")
                break

    except KeyboardInterrupt:
        print("\n🛑 Interrupted")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 CTRL + C → exit")
    print("=" * 60)
