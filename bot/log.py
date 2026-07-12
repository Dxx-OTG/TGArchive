"""Timestamped logging: prints to the console AND appends to a daily file under log/.

One file per day (log/tgarchive-YYYY-MM-DD.log), every line prefixed with the date and time of the
action. These files are LOCAL only: gitignored, wiped by Prepare Transfer, and cleanable from the menu
(Clean Logs/History -> a separate y/n for the log files). Writing to the file never breaks the bot -
any filesystem error is swallowed and logging falls back to console-only.
"""
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "log"


def _log_file(now: datetime) -> Path:
    return LOG_DIR / f"tgarchive-{now:%Y-%m-%d}.log"


def log(message: str) -> None:
    now = datetime.now()
    line = f"[{now:%Y-%m-%d %H:%M:%S}] {message}"
    try:
        print(line)
    except UnicodeEncodeError:
        # A non-UTF-8 console (cp1252) can't print emojis; don't let that abort logging.
        print(line.encode("ascii", "replace").decode("ascii"))
    try:
        LOG_DIR.mkdir(exist_ok=True)
        with open(_log_file(now), "a", encoding="utf-8") as f:  # the file always keeps full UTF-8
            f.write(line + "\n")
    except OSError:
        pass  # a logging failure must never take the bot down
