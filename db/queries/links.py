from datetime import datetime

import asyncpg

from bot.group_links import link_display, link_key
from db.blacklist import resolve_blacklist


def _display_key(link: str) -> str:
    """Sort key = the clean displayed name (link_display), casefolded. Links MUST sort by what the
    user actually sees: sorting by the full URL split http:// before https:// (and t.me before
    telegram.me), scattering the list into scheme-blocks even though the visible names are the same.
    Sorting by link_display (the exact display function) keeps order == display, scheme-independent."""
    return link_display(link).casefold()


def _grouped_key(row) -> tuple[str, str]:
    """Sort key for a link list grouped by source: (source group title, clean link name) - both
    casefolded so grouping and within-group order are predictable and match the rendered labels."""
    return ((row["group_title"] or "").casefold(), _display_key(row["link"]))


async def insert_link(
    pool: asyncpg.Pool,
    *,
    group_id: int,
    link: str,
    sender_user_id: int | None = None,
    sender_username: str | None = None,
    message_date: datetime | None = None,
) -> None:
    await pool.execute(
        """
        INSERT INTO extracted_links (group_id, link, link_key, sender_user_id, sender_username, message_date)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (group_id, link_key) DO UPDATE SET link = EXCLUDED.link
        """,
        group_id, link, link_key(link), sender_user_id, sender_username, message_date,
    )


def _sharers_col(alias: str) -> str:
    """SQL for the `sharers` column: how many DISTINCT users shared this link (by link_key) across the
    whole archive. The table keeps one sender per (group, link_key), so a per-group count is always 1;
    the useful 'shared by N people' is archive-wide. Drives the clickable 👤 N on link lists."""
    return (f"(SELECT count(DISTINCT s.sender_user_id) FROM extracted_links s "
            f"WHERE s.link_key = {alias}.link_key AND s.sender_user_id IS NOT NULL) AS sharers")


async def links_for_group(pool: asyncpg.Pool, group_id: int) -> list[asyncpg.Record]:
    """The links shared in one group, ordered by their clean display name, for the paginated links
    drill-in. Blacklisted links (blacklisted sender/target) are excluded."""
    bl = await resolve_blacklist(pool)
    rows = await pool.fetch(
        f"""
        SELECT link, sender_username, message_date, {_sharers_col('extracted_links')}
        FROM extracted_links
        WHERE group_id = $1
          AND id != ALL($2::bigint[])
        ORDER BY id
        """,
        group_id, bl.link_ids,
    )
    return sorted(rows, key=lambda r: _display_key(r["link"]))


# The source-group columns every link list carries, so the UI can group links by the channel/group
# they were shared in (alphabetically), then alphabetically within each group. Blacklisted excluded.
_LINK_GROUP_COLS = (
    "el.link, el.sender_username, "
    "g.title AS group_title, g.username AS group_username, g.invite_input AS group_invite, g.kind AS group_kind, "
    + _sharers_col("el")
)


async def list_all_links(pool: asyncpg.Pool) -> list[asyncpg.Record]:
    """Every extracted link, grouped by source group then by clean link name (both alphabetical), for
    the stats drill-down. Blacklisted links are excluded so the list matches the count."""
    bl = await resolve_blacklist(pool)
    rows = await pool.fetch(
        f"""
        SELECT {_LINK_GROUP_COLS}
        FROM extracted_links el
        JOIN groups g ON g.id = el.group_id
        WHERE el.id != ALL($1::bigint[])
        ORDER BY el.id
        """,
        bl.link_ids,
    )
    return sorted(rows, key=_grouped_key)


async def search_links(pool: asyncpg.Pool, query: str) -> list[asyncpg.Record]:
    """Links whose URL contains `query` (case-insensitive), deduped by link_key so the same link
    shared in several groups shows once, in alphabetical (URL) order. Blacklisted links excluded.
    Backs the hub/CLI link search. `%`/`_` in the query are escaped so they match literally."""
    bl = await resolve_blacklist(pool)
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    rows = await pool.fetch(
        f"""
        SELECT link, sender_username, group_title, group_username, group_invite, group_kind FROM (
            SELECT DISTINCT ON (el.link_key)
                {_LINK_GROUP_COLS}
            FROM extracted_links el
            JOIN groups g ON g.id = el.group_id
            WHERE el.link ILIKE '%' || $1 || '%'
              AND el.id != ALL($2::bigint[])
            ORDER BY el.link_key, el.id
        ) t
        """,
        escaped, bl.link_ids,
    )
    return sorted(rows, key=_grouped_key)


async def links_by_user(pool: asyncpg.Pool, tg_user_id: int) -> list[asyncpg.Record]:
    """The links a given user shared, grouped by source group then by clean link name (both
    alphabetical), for the user card/detail. Blacklisted links are excluded."""
    bl = await resolve_blacklist(pool)
    rows = await pool.fetch(
        f"""
        SELECT {_LINK_GROUP_COLS}
        FROM extracted_links el
        JOIN groups g ON g.id = el.group_id
        WHERE el.sender_user_id = $1
          AND el.id != ALL($2::bigint[])
        ORDER BY el.id
        """,
        tg_user_id, bl.link_ids,
    )
    return sorted(rows, key=_grouped_key)
