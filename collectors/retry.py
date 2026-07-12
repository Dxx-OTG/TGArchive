import asyncio
import random
from typing import Awaitable, Callable

from telethon.errors import FloodWaitError
from telethon.errors.rpcerrorlist import RPCError

from .throttle import MAX_FLOOD_WAIT

MAX_RETRIES = 3


async def run_with_retry(attempt_fn: Callable[[], Awaitable[None]], max_retries: int = MAX_RETRIES) -> bool:
    """Retry attempt_fn on FloodWaitError/RPCError. attempt_fn mutates shared state via closure, so
    partial progress survives a failed attempt. Returns True if one attempt finished cleanly."""
    for attempt in range(max_retries):
        try:
            await attempt_fn()
            return True

        except FloodWaitError as e:
            # A long FloodWait means Telegram is throttling this account: stop and keep what we have
            # instead of sleeping it off (which would freeze the shared client) or retrying (which
            # makes it worse). Short waits are safe to ride out.
            if e.seconds > MAX_FLOOD_WAIT:
                print(f"⛔ FloodWait {e.seconds}s exceeds the {MAX_FLOOD_WAIT}s cap - stopping to "
                      "protect the account, saving what I have")
                return False
            print(f"⚠️ FloodWait: waiting {e.seconds}s")
            await asyncio.sleep(e.seconds)

        except RPCError as e:
            print(f"⚠️ RPCError: {e.message}")
            if attempt < max_retries - 1:
                await asyncio.sleep(random.uniform(2, 5))
            else:
                print("❌ Too many errors, saving what I have")
                return False

        except Exception as e:
            print(f"❌ Error: {e}")
            return False

    return False
