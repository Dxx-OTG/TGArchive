"""One-Telethon-job-at-a-time gate, shared by every bot command that drives the single scraping
client (scrape + check). The scrapers and the reachability check all talk to the *same* Telethon
session, so only one may run at a time; this also carries the cooldown that keeps back-to-back jobs
from hammering the account.
"""
import asyncio
import time

from collectors.throttle import JOB_COOLDOWN_SECONDS

_job_lock = asyncio.Lock()
# Monotonic time the last job finished, to enforce JOB_COOLDOWN_SECONDS between jobs.
_last_job_at = 0.0


async def acquire_job() -> bool:
    """Claim the single-job slot atomically. Returns False if a job is already running. The
    locked() check and acquire() have no await between them, so two near-simultaneous commands can't
    both slip past (one would otherwise queue and run right after the other)."""
    if _job_lock.locked():
        return False
    await _job_lock.acquire()
    return True


async def cooldown_wait() -> None:
    """Sleep off whatever remains of JOB_COOLDOWN_SECONDS since the previous job finished."""
    gap = JOB_COOLDOWN_SECONDS - (time.monotonic() - _last_job_at)
    if gap > 0:
        await asyncio.sleep(gap)


def release_job() -> None:
    """Release the slot and stamp the finish time for the next job's cooldown."""
    global _last_job_at
    _last_job_at = time.monotonic()
    _job_lock.release()
