from telethon import TelegramClient

from .config import load_config
from .throttle import FLOOD_SLEEP_THRESHOLD


class _CountingClient(TelegramClient):
    """Every high-level call (get_entity, iter_messages, CheckChatInvite, …) ends up as one or more raw
    requests through __call__, so counting here catches EVERY outgoing Telegram RPC exactly once - the
    terminal then shows what each action costs (collectors/api_counter.py)."""

    async def __call__(self, request, *args, **kwargs):
        from collectors.api_counter import note_call
        note_call(request)
        return await super().__call__(request, *args, **kwargs)


def create_client() -> TelegramClient:
    config = load_config()
    return _CountingClient(
        config["session"],
        config["api_id"],
        config["api_hash"],
        # Let Telethon ride out short FloodWaits itself; longer ones reach collectors/retry.py,
        # which decides whether to wait or abort. Set explicitly so the policy lives in one place.
        flood_sleep_threshold=FLOOD_SLEEP_THRESHOLD,
    )
