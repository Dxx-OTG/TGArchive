"""Central knobs for how gently the scraping account talks to Telegram.

Every scraper imports its pacing from here so the whole project stays "polite" in one place: change
a value here and members/messages/links scraping and the bot's job pacing all follow. The goal is to
avoid FloodWait/account limits caused by bursts of automatic API calls.
"""
import random

# Telethon auto-sleeps FloodWaits up to this many seconds on its own (inside get_participants/
# iter_messages); longer ones surface as FloodWaitError and reach collectors/retry.py.
FLOOD_SLEEP_THRESHOLD = 60

# A FloodWaitError longer than this is treated as "stop", not "wait": retry.py aborts the attempt
# (saving partial progress) instead of sleeping it off. A multi-minute/hour wait is Telegram telling
# us to back off - sleeping the whole time would freeze the single shared Telethon client, and
# retrying only digs the hole deeper.
MAX_FLOOD_WAIT = 300

# Pause inserted periodically while paginating messages or participants, to spread requests out.
PAGE_SLEEP_MIN = 0.5
PAGE_SLEEP_MAX = 1.5

# Throttle the participant list the same way as messages: pause once every N participants read.
PARTICIPANTS_SLEEP_EVERY = 2000

# Minimum gap (seconds) the bot enforces between two consecutive scrape jobs, so commands fired
# back-to-back don't hammer the account. The CLI tools already sleep between groups; this gives the
# bot the same breathing room.
JOB_COOLDOWN_SECONDS = 8

# Check reachability probing (collectors/check.py): one resolve per entity, but a whole run can probe
# many *different* entities back-to-back - a pattern closer to a scan than to paging one chat, and the
# resolve call (ResolveUsername/CheckChatInvite) is what Telegram rate-limits hardest. So it gets its
# own, cautious gap. Kept here so all pacing lives in one place.
CHECK_SLEEP_MIN = 3.0
CHECK_SLEEP_MAX = 6.0

# Hard cap on how many entities ONE Check All / Check Links run will probe. Resolving hundreds of
# never-seen entities in a row is exactly what trips a long FloodWait; capping each run keeps it under
# the threshold. The rest stays ▫️ unchecked and is picked up by running again - "Skip recent" resumes
# with the oldest-checked first, so a few runs (or a few days, thanks to the 24h cache) cover them all.
MAX_CHECK_PER_RUN = 40

# A stored check result younger than this is reused by Check All instead of re-probing (unless
# `force`), so running the command a few times a day doesn't re-hit Telegram for every entity.
CHECK_STATUS_TTL_HOURS = 24


def page_sleep_seconds() -> float:
    """A small randomized pause for use between pages of a paginated read."""
    return random.uniform(PAGE_SLEEP_MIN, PAGE_SLEEP_MAX)


def check_sleep_seconds() -> float:
    """A cautious randomized pause between two reachability probes in Check All."""
    return random.uniform(CHECK_SLEEP_MIN, CHECK_SLEEP_MAX)


def floodwait_seconds(exc) -> int | None:
    """The wait in seconds if `exc` is (or wraps, via __cause__/__context__) a Telegram FloodWait,
    else None. Used so every surface can tell a rate-limit apart from a generic error and show it."""
    from telethon.errors import FloodWaitError
    seen = set()
    e = exc
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        if isinstance(e, FloodWaitError):
            return int(getattr(e, "seconds", 0) or 0)
        e = getattr(e, "__cause__", None) or getattr(e, "__context__", None)
    return None


def format_wait(seconds: int | None) -> str:
    """A short human wait, e.g. '45s', '12m', '1h 15m'; 'a while' when the exact time is unknown."""
    if not seconds or seconds <= 0:
        return "a while"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if minutes else f"{hours}h"
