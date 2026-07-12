"""Typed scrape failure reasons, so the bot and CLI can show the exact cause of a failed scrape
instead of one generic 'couldn't scrape'. The scrapers (CLI/Scrape.py, CLI/Messages.py,
CLI/ExtractLinks.py) raise ScrapeError; each front-end maps the reason to its own wording."""

NOT_FOUND = "not_found"        # the entity couldn't be resolved (gone, wrong handle, bad/expired invite)
NOT_MEMBER = "not_member"      # a valid private group/channel the scraping account hasn't joined yet
WRONG_TYPE = "wrong_type"      # resolved, but not a kind this scrape can read (e.g. members of a channel)
EMPTY = "empty"                # resolved fine, but nothing to collect this run
RATE_LIMITED = "rate_limited"  # Telegram throttled us (FloodWait over the cap / too many errors)


class ScrapeError(Exception):
    """A scrape that failed for a known, user-explainable reason. `detail` carries optional context
    (e.g. the resolved entity's kind label for WRONG_TYPE) for a more specific message."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(reason)
        self.reason = reason
        self.detail = detail
