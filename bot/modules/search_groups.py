"""Group/channel search helpers for the /start hub's in-place Search (bot/modules/start.py): the
search + header the hub renders. No router — this module registers no handlers.
"""
from html import escape

from bot.group_links import dedupe_groups, group_link
from bot.i18n import plural, t
from db.queries import groups as groups_q


async def _search(pool, query: str, db_kind: str) -> list:
    rows = await groups_q.search_groups_by_name(pool, query, db_kind)
    return dedupe_groups(
        rows,
        link_fn=lambda r: group_link(r["username"], r["invite_input"]),
        score_fn=lambda r: r["members"],
    )


def _header(query: str, n: int) -> str:
    return t("searchgroups_found", n=n, word=plural(n, "Result", "Results"), query=escape(query))
