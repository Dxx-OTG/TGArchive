from telethon import TelegramClient

from bot.log import log
from collectors.api_counter import set_sink as _set_api_sink
from collectors.telethon_client import create_client
from collectors.telethon_lock import TelethonSessionBusy, acquire_telethon_lock, release_telethon_lock

_client: TelegramClient | None = None
_unavailable_reason: str | None = None

# Send the per-call "[Telegram API #N] ..." lines through the bot's logger, so every outgoing call
# shows on the bot terminal (and lands in the log file) with a timestamp.
_set_api_sink(log)


async def init_scrape_client() -> TelegramClient | None:
    """Connect the Telethon client used by the scrape flows (hub, card, and the CLI scrapers). Never logs
    in interactively - if the session isn't already authorized, scraping just stays disabled instead
    of blocking bot startup. Called once by bot/main.py at startup."""
    global _client, _unavailable_reason

    try:
        client = create_client()
    except RuntimeError as e:
        _unavailable_reason = str(e)
        log(f"⚠️ Scraping commands disabled: {_unavailable_reason}")
        return None

    try:
        acquire_telethon_lock()
    except TelethonSessionBusy as e:
        _unavailable_reason = str(e)
        log(f"⚠️ Scraping commands disabled: {_unavailable_reason}")
        return None

    try:
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            release_telethon_lock()
            _unavailable_reason = (
                "Telethon session not authorized yet. Run the CLI once to log in "
                "(phone + OTP), then restart the bot."
            )
            log(f"⚠️ Scraping commands disabled: {_unavailable_reason}")
            return None
    except Exception as e:
        release_telethon_lock()
        _unavailable_reason = f"cannot connect to Telegram: {e}"
        log(f"⚠️ Scraping commands disabled: {_unavailable_reason}")
        return None

    _client = client
    log("🔌 Scraping commands enabled (Telethon session connected).")
    return _client


async def get_scrape_client() -> TelegramClient:
    """Raises RuntimeError with a user-facing reason if scraping is unavailable. Reconnects on its
    own if the connection was dropped."""
    if _client is None:
        raise RuntimeError(_unavailable_reason or "Scraping client not initialized")

    if not _client.is_connected():
        log("🔌 Scraping client was disconnected, reconnecting...")
        try:
            await _client.connect()
        except Exception as e:
            raise RuntimeError(f"cannot reconnect to Telegram: {e}") from e

    return _client


async def close_scrape_client() -> None:
    global _client
    if _client is not None:
        await _client.disconnect()
        release_telethon_lock()
        _client = None
