"""Group/channel list helpers for the /start hub's Browse and Stats (bot/modules/start.py): the load +
header the hub renders in place. No router — this module registers no handlers.
"""
from bot.group_links import dedupe_groups, group_link
from bot.i18n import plural, t
from db.queries import groups as groups_q


async def _load(pool, kind: str) -> list:
    """Scraped entities of one kind (blacklisted dropped in the query), duplicate rows collapsed."""
    rows = await groups_q.list_groups_with_counts(pool, kind)
    return dedupe_groups(
        rows,
        link_fn=lambda r: group_link(r["username"], r["invite_input"]),
        score_fn=lambda r: r["members"],
    )


def _header(kind: str, n: int) -> str:
    if kind == "channel":
        return t("channels_list_header", n=n, word=plural(n, "Scraped Channel", "Scraped Channels"))
    return t("groups_list_header", n=n, word=plural(n, "Scraped Group", "Scraped Groups"))
