"""Scrape input parsing shared by the hub/card scrape flows.

Scraping is driven from the /start hub (Scrape) and the entity card, both of which run the job in
place via start.run_scrape_inplace; this module provides the small input parser they share. No
router — this module registers no handlers.
"""


def _split_group_and_limit(args: str | None, default_limit: int, max_limit: int) -> tuple[str, int]:
    """'<group> [limit]' -> (group, limit). A trailing numeric token is the limit, capped at max_limit."""
    parts = (args or "").split()
    if parts and parts[-1].isdigit():
        return " ".join(parts[:-1]), min(int(parts[-1]), max_limit)
    return " ".join(parts), default_limit
