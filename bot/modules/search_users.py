"""User search helper for the /start hub's in-place Search (bot/modules/start.py): the query->people
resolution the hub calls. No router — this module registers no handlers.
"""
from bot.querykind import QueryKind, classify_query
from db.queries import members as members_q


async def _fetch_people(pool, raw_query: str, *, bots: bool = False) -> list:
    """Resolve a Users (bots=False) / Bots (bots=True) search query into people rows, auto-detecting the
    input kind (id / @username / free-text substring). A bot is a user whose @username ends in 'bot', so
    an id/@username hit is kept only if its bot-ness matches the category searched."""
    from bot.entitykind import is_bot_username
    kind, value = classify_query(raw_query)
    if kind is QueryKind.ID:
        rows = await members_q.people_by_id(pool, int(value))
    elif kind is QueryKind.USERNAME:
        rows = await members_q.people_by_username(pool, value)
    else:
        return await members_q.search_member_people(pool, value, bots=bots)
    return [r for r in rows if is_bot_username(r["username"]) == bots]
