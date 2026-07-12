import re

import asyncpg

from bot.group_links import normalize_query
from db.blacklist import is_user_blacklisted, resolve_blacklist

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{5,32}$")

# A bot's @username always ends in 'bot' (Telegram rule) and a bot always HAS a username, so we split
# users vs bots locally from the username alone - no is_bot column, works on existing data. See
# collectors.entitykind.is_bot_username (the same rule, for live entities). `col` is the username column
# (e.g. 'm.username') so the same condition works across the different query aliases.
def _kind_cond(col: str, bots: bool) -> str:
    return f"lower({col}) LIKE '%bot'" if bots else f"({col} IS NULL OR lower({col}) NOT LIKE '%bot')"


async def upsert_member(pool: asyncpg.Pool, *, tg_user_id: int, username: str | None = None) -> int:
    return await pool.fetchval(
        """
        INSERT INTO members (tg_user_id, username)
        VALUES ($1, $2)
        ON CONFLICT (tg_user_id) DO UPDATE SET
            username = COALESCE(EXCLUDED.username, members.username),
            last_seen_at = now()
        RETURNING id
        """,
        tg_user_id, username,
    )


async def link_group_member(pool: asyncpg.Pool, *, group_id: int, member_id: int, source: str) -> None:
    await pool.execute(
        """
        INSERT INTO group_members (group_id, member_id, source)
        VALUES ($1, $2, $3)
        ON CONFLICT (group_id, member_id, source) DO UPDATE SET
            last_seen_at = now()
        """,
        group_id, member_id, source,
    )


async def find_member_groups(pool: asyncpg.Pool, query: str) -> list[asyncpg.Record]:
    """Groups a user is in, by tg_user_id (if numeric) or exact username. A blacklisted user resolves
    to nothing (excluded via member id), and blacklisted groups are dropped from the list."""
    query = normalize_query(query)
    bl = await resolve_blacklist(pool)

    if query.isdigit():
        return await pool.fetch(
            """
            SELECT g.title, g.username AS group_username, g.invite_input, gm.source, m.tg_user_id, m.username
            FROM group_members gm
            JOIN groups g ON g.id = gm.group_id
            JOIN members m ON m.id = gm.member_id
            WHERE m.tg_user_id = $1
              AND m.id != ALL($2::bigint[])
              AND gm.group_id != ALL($3::bigint[])
            ORDER BY lower(g.title)
            """,
            int(query), bl.member_ids, bl.group_ids,
        )

    if not USERNAME_RE.match(query):
        return []

    return await pool.fetch(
        """
        SELECT g.title, g.username AS group_username, g.invite_input, gm.source, m.tg_user_id, m.username
        FROM group_members gm
        JOIN groups g ON g.id = gm.group_id
        JOIN members m ON m.id = gm.member_id
        WHERE lower(m.username) = lower($1)
          AND m.id != ALL($2::bigint[])
          AND gm.group_id != ALL($3::bigint[])
        ORDER BY lower(g.title)
        """,
        query, bl.member_ids, bl.group_ids,
    )


async def find_member(pool: asyncpg.Pool, *, username: str | None = None, tg_user_id: int | None = None) -> asyncpg.Record | None:
    """One member by exact id or exact (case-insensitive) username, regardless of group membership.
    A blacklisted member resolves to None (as if not in the archive)."""
    if tg_user_id is not None:
        row = await pool.fetchrow("SELECT tg_user_id, username FROM members WHERE tg_user_id = $1", tg_user_id)
    elif username:
        handle = normalize_query(username)
        if not handle:
            return None
        row = await pool.fetchrow("SELECT tg_user_id, username FROM members WHERE lower(username) = lower($1)", handle)
    else:
        return None

    if row is not None and is_user_blacklisted(row["tg_user_id"], row["username"]):
        return None
    return row


async def search_member_people(pool: asyncpg.Pool, query: str, *, bots: bool = False, limit: int = 500) -> list[asyncpg.Record]:
    """People (bots=False) or bots (bots=True) whose username contains `query` (case-insensitive), one
    row each with group and link counts, for the paginated Search results. Blacklisted users are
    excluded, and both counts exclude anything blacklisted so they match what actually shows."""
    query = normalize_query(query)
    bl = await resolve_blacklist(pool)
    return await pool.fetch(
        f"""
        SELECT tg_user_id, username, num_groups, num_links FROM (
            SELECT m.tg_user_id, m.username, count(DISTINCT gm.group_id) AS num_groups,
                   (SELECT count(*) FROM extracted_links el WHERE el.sender_user_id = m.tg_user_id AND el.id != ALL($3::bigint[])) AS num_links
            FROM group_members gm
            JOIN members m ON m.id = gm.member_id
            WHERE m.username ILIKE '%' || $1 || '%'
              AND {_kind_cond("m.username", bots)}
              AND m.id != ALL($4::bigint[])
              AND gm.group_id != ALL($5::bigint[])
            GROUP BY m.id
            UNION
            SELECT m.tg_user_id, m.username, 0 AS num_groups,  -- standalone (registered) member, no group
                   (SELECT count(*) FROM extracted_links el WHERE el.sender_user_id = m.tg_user_id AND el.id != ALL($3::bigint[])) AS num_links
            FROM members m
            WHERE m.username ILIKE '%' || $1 || '%'
              AND m.id NOT IN (SELECT DISTINCT member_id FROM group_members)
              AND {_kind_cond("m.username", bots)}
              AND m.id != ALL($4::bigint[])
        ) t
        ORDER BY (username IS NULL), lower(username), tg_user_id
        LIMIT $2
        """,
        query, limit, bl.link_ids, bl.member_ids, bl.group_ids,
    )


async def list_people(pool: asyncpg.Pool, *, bots: bool = False) -> list[asyncpg.Record]:
    """Every user (bots=False) or bot (bots=True) with their group and shared-link counts (same shape as
    search_member_people), for the Browse Users / Browse Bots list. Blacklisted users/groups excluded
    from both the listing and the counts."""
    bl = await resolve_blacklist(pool)
    return await pool.fetch(
        f"""
        SELECT tg_user_id, username, num_groups, num_links FROM (
            SELECT m.tg_user_id, m.username, count(DISTINCT gm.group_id) AS num_groups,
                   (SELECT count(*) FROM extracted_links el WHERE el.sender_user_id = m.tg_user_id AND el.id != ALL($1::bigint[])) AS num_links
            FROM group_members gm
            JOIN members m ON m.id = gm.member_id
            WHERE {_kind_cond("m.username", bots)}
              AND m.id != ALL($2::bigint[])
              AND gm.group_id != ALL($3::bigint[])
            GROUP BY m.id
            UNION
            SELECT m.tg_user_id, m.username, 0 AS num_groups,  -- standalone (registered) member, no group
                   (SELECT count(*) FROM extracted_links el WHERE el.sender_user_id = m.tg_user_id AND el.id != ALL($1::bigint[])) AS num_links
            FROM members m
            WHERE m.id NOT IN (SELECT DISTINCT member_id FROM group_members)
              AND {_kind_cond("m.username", bots)}
              AND m.id != ALL($2::bigint[])
        ) t
        ORDER BY (username IS NULL), lower(username), tg_user_id
        """,
        bl.link_ids, bl.member_ids, bl.group_ids,
    )


async def link_sharers(pool: asyncpg.Pool, key: str) -> list[asyncpg.Record]:
    """The distinct users who shared a link (matched by link_key) across the whole archive, for the
    👤 sharers-count drill-down on link lists. sender_user_id/sender_username come straight from the
    link rows (a sharer need not be a scraped member). Blacklisted senders excluded."""
    bl = await resolve_blacklist(pool)
    return await pool.fetch(
        """
        SELECT tg_user_id, username FROM (
            SELECT DISTINCT el.sender_user_id AS tg_user_id, el.sender_username AS username
            FROM extracted_links el
            WHERE el.link_key = $1
              AND el.sender_user_id IS NOT NULL
              AND el.id != ALL($2::bigint[])
        ) t
        ORDER BY (username IS NULL), lower(username), tg_user_id
        """,
        key, bl.link_ids,
    )


async def people_by_id(pool: asyncpg.Pool, tg_user_id: int) -> list[asyncpg.Record]:
    """The one person with this exact id (0 or 1 rows), same shape as search_member_people. Empty if
    that user is blacklisted or only in blacklisted groups."""
    bl = await resolve_blacklist(pool)
    return await pool.fetch(
        """
        SELECT m.tg_user_id, m.username, count(DISTINCT gm.group_id) AS num_groups,
               (SELECT count(*) FROM extracted_links el WHERE el.sender_user_id = m.tg_user_id AND el.id != ALL($2::bigint[])) AS num_links
        FROM group_members gm
        JOIN members m ON m.id = gm.member_id
        WHERE m.tg_user_id = $1
          AND m.id != ALL($3::bigint[])
          AND gm.group_id != ALL($4::bigint[])
        GROUP BY m.id
        """,
        tg_user_id, bl.link_ids, bl.member_ids, bl.group_ids,
    )


async def people_by_username(pool: asyncpg.Pool, username: str) -> list[asyncpg.Record]:
    """People whose username equals `username` exactly (case-insensitive). Almost always 0 or 1, but a
    handle can be reused across accounts over time, hence a list. Blacklisted users excluded."""
    username = normalize_query(username)
    bl = await resolve_blacklist(pool)
    return await pool.fetch(
        """
        SELECT m.tg_user_id, m.username, count(DISTINCT gm.group_id) AS num_groups,
               (SELECT count(*) FROM extracted_links el WHERE el.sender_user_id = m.tg_user_id AND el.id != ALL($2::bigint[])) AS num_links
        FROM group_members gm
        JOIN members m ON m.id = gm.member_id
        WHERE lower(m.username) = lower($1)
          AND m.id != ALL($3::bigint[])
          AND gm.group_id != ALL($4::bigint[])
        GROUP BY m.id
        ORDER BY lower(m.username), m.tg_user_id
        """,
        username, bl.link_ids, bl.member_ids, bl.group_ids,
    )


async def list_members(pool: asyncpg.Pool, which: str = "all") -> list[asyncpg.Record]:
    """Members for the Stats drill-downs. which='all'/'with'/'without' cover USERS (non-bots), split by
    whether they have a username; which='bots' covers the bots. Named users first, alphabetically, then
    the username-less ones. Blacklisted members are excluded, so the list matches the Stats count."""
    bl = await resolve_blacklist(pool)
    if which == "bots":
        conds = ["id != ALL($1::bigint[])", _kind_cond("username", True)]
    else:
        conds = ["id != ALL($1::bigint[])", _kind_cond("username", False)]
        if which == "with":
            conds.append("username IS NOT NULL")
        elif which == "without":
            conds.append("username IS NULL")
    where = "WHERE " + " AND ".join(conds)
    return await pool.fetch(
        f"""
        SELECT tg_user_id, username
        FROM members
        {where}
        ORDER BY (username IS NULL), lower(username), tg_user_id
        """,
        bl.member_ids,
    )


async def count_members_by_kind(pool: asyncpg.Pool) -> asyncpg.Record:
    """Member totals for Stats: users vs bots (by the username rule), and for users the with/without a
    username split. Blacklisted members excluded."""
    bl = await resolve_blacklist(pool)
    return await pool.fetchrow(
        f"""
        SELECT
            count(*) FILTER (WHERE {_kind_cond("username", False)}) AS users,
            count(*) FILTER (WHERE {_kind_cond("username", True)}) AS bots,
            count(*) FILTER (WHERE {_kind_cond("username", False)} AND username IS NOT NULL) AS with_username,
            count(*) FILTER (WHERE {_kind_cond("username", False)} AND username IS NULL) AS without_username
        FROM members
        WHERE id != ALL($1::bigint[])
        """,
        bl.member_ids,
    )


async def list_group_members(pool: asyncpg.Pool, group_id: int) -> list[asyncpg.Record]:
    """One row per unique member of a group, used by export. A user seen via both sources
    (participants list AND message senders) is a single row with both joined in `source` (e.g.
    'messages,participants'). Blacklisted members are excluded so the export matches the counts."""
    bl = await resolve_blacklist(pool)
    return await pool.fetch(
        """
        SELECT m.tg_user_id, m.username,
               string_agg(DISTINCT gm.source::text, ',' ORDER BY gm.source::text) AS source
        FROM group_members gm
        JOIN members m ON m.id = gm.member_id
        WHERE gm.group_id = $1
          AND gm.member_id != ALL($2::bigint[])
        GROUP BY m.id
        ORDER BY (m.username IS NULL), lower(m.username), m.tg_user_id
        """,
        group_id, bl.member_ids,
    )


async def list_distinct_group_members(pool: asyncpg.Pool, group_id: int) -> list[asyncpg.Record]:
    """One row per unique user in a group (collapses the participants/messages duplicate), used by
    the paginated members list. Named users first, alphabetically, then the username-less ones.
    Blacklisted members are excluded. GROUP BY m.id (the PK) rather than SELECT DISTINCT so the
    ORDER BY can use expressions that aren't in the select list."""
    bl = await resolve_blacklist(pool)
    return await pool.fetch(
        """
        SELECT m.tg_user_id, m.username
        FROM group_members gm
        JOIN members m ON m.id = gm.member_id
        WHERE gm.group_id = $1
          AND gm.member_id != ALL($2::bigint[])
        GROUP BY m.id
        ORDER BY (m.username IS NULL), lower(m.username), m.tg_user_id
        """,
        group_id, bl.member_ids,
    )
