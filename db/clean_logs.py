"""Interactive log & cache cleanup (clean_logs.bat / menu Clean Logs/History).

Deletes, each after its own explicit "y": the local operational log files under log/, the
reachability-check cache (output/.check_status.json), and the resolve cache
(output/.resolve_cache.json). Purely a filesystem cleanup: no database connection, and it never
touches scraped CSVs or favorites. Pagination/card tokens live only in RAM and reset on a bot restart.
"""
from pathlib import Path

PREVIEW_MAX_ROWS = 30
ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "log"
CHECK_CACHE = ROOT / "output" / ".check_status.json"
RESOLVE_CACHE = ROOT / "output" / ".resolve_cache.json"


def clean_log_files(log_dir: Path) -> None:
    """List the local log files and, on a "y", delete them."""
    files = sorted(log_dir.glob("*.log")) if log_dir.exists() else []
    if not files:
        print("log files: nothing to delete.")
        return

    total_kb = sum(f.stat().st_size for f in files) / 1024
    print(f"--- log files: {len(files)} file(s) in {log_dir.name}\\ ({total_kb:.0f} KB) ---")
    for f in files[:PREVIEW_MAX_ROWS]:
        print(f.name)
    if len(files) > PREVIEW_MAX_ROWS:
        print(f"... and {len(files) - PREVIEW_MAX_ROWS} more files")

    answer = input(f"Delete these {len(files)} log file(s) from {log_dir.name}\\? (y/n): ")
    if answer.strip().lower() != "y":
        print("Skipped.")
        return

    deleted = 0
    for f in files:
        try:
            f.unlink()
            deleted += 1
        except OSError as e:
            print(f"  could not remove {f.name}: {e}")
    print(f"log files: {deleted} file(s) deleted.")


def clean_cache_file(cache_file: Path, label: str, describe: str, warn: str) -> None:
    """Offer to delete one cache file (nothing else is touched). `describe` says what it holds, `warn`
    what re-doing it costs."""
    if not cache_file.exists():
        print(f"{label}: nothing to delete.")
        return

    kb = cache_file.stat().st_size / 1024
    print(f"--- {label}: {cache_file.name} ({kb:.0f} KB) - {describe} ---")
    if input(f"Delete the {label}? {warn} (y/n): ").strip().lower() != "y":
        print("Skipped.")
        return
    try:
        cache_file.unlink()
        print(f"{label}: deleted.")
    except OSError as e:
        print(f"  could not remove {cache_file.name}: {e}")


def main() -> None:
    clean_log_files(LOG_DIR)
    print()
    clean_cache_file(CHECK_CACHE, "check cache", "the 24h reachability results",
                     "The next Check will re-probe everything.")
    print()
    clean_cache_file(RESOLVE_CACHE, "resolve cache", "24h resolved-link identities (reopened cards)",
                     "Reopening an unsaved link will re-resolve it live.")
    print()
    print("Note: the resolve cache is reloaded into the bot at startup, so for a fully clean start "
          "close the bot before deleting it (a running bot can rewrite the file). Pagination/card "
          "tokens live only in RAM and always reset when the bot restarts.")


if __name__ == "__main__":
    main()
