import os

from dotenv import load_dotenv

load_dotenv()


def load_config() -> dict:
    """Telethon credentials (scraping account) read from .env, shared by every scraper."""
    api_id = os.environ.get("TG_API_ID")
    api_hash = os.environ.get("TG_API_HASH")
    session = os.environ.get("TG_SESSION_NAME")

    if not api_id or not api_hash or not session:
        raise RuntimeError("TG_API_ID / TG_API_HASH / TG_SESSION_NAME missing in .env")

    return {"api_id": int(api_id), "api_hash": api_hash, "session": session}
