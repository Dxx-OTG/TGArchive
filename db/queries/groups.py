import asyncpg

from bot.group_links import canonical_group_key, extract_username, group_link, normalize_query
from db.blacklist import resolve_blacklist


async def search_groups_by_name(pool: asyncpg.Pool, query: str, kind: str = "group") -> list[asyncpg.Record]:
    """Search entities of one kind ('group' or 'channel') by
    case-insensitive substring on title/username/invite_input, with member and link counts. g.username
    is almost always NULL (CSV import never fills it), so matching invite_input is what counts.
    Blacklisted groups are dropped and their blacklisted members/links excluded from the counts."""
    query = normalize_query(query)
    bl = await resolve_blacklist(pool)
    return await pool.fetch(
        """
        SELECT g.id, g.title, g.username, g.invite_input, g.kind,
               count(DISTINCT gm.member_id) FILTER (WHERE gm.member_id != ALL($4::bigint[])) AS members,
               (SELECT count(*) FROM extracted_links el WHERE el.group_id = g.id AND el.id != ALL($5::bigint[])) AS links
        FROM groups g
        LEFT JOIN group_members gm ON gm.group_id = g.id
        WHERE g.kind = $2
          AND g.id != ALL($3::bigint[])
          AND (g.title ILIKE '%' || $1 || '%' OR g.username ILIKE '%' || $1 || '%' OR g.invite_input ILIKE '%' || $1 || '%')
        GROUP BY g.id
        ORDER BY lower(g.title)
        """,
        query, kind, bl.group_ids, bl.member_ids, bl.link_ids,
    )


async def find_group_by_exact_username(pool: asyncpg.Pool, raw: str, kind: str | None = None) -> asyncpg.Record | None:
    """Resolve a group by its EXACT public username, used by the members view and export so a query like
    'i' can't pull in every group whose name contains an 'i'. The query is normalized to a bare
    handle (an @ or t.me link is accepted and stripped), then matched against each group's username
    derived from its username column or invite_input. Groups with no public username aren't
    reachable this way - that's intended. On duplicates, the one with the most members wins.
    kind filters to 'group'/'channel' (group vs channel search); None matches any."""
    target = normalize_query(raw).lower()
    if not target:
        return None
    bl = await resolve_blacklist(pool)
    rows = await pool.fetch(
        """
        SELECT g.id, g.title, g.username, g.invite_input, g.tg_chat_id, g.kind,
               count(DISTINCT gm.member_id) FILTER (WHERE gm.member_id != ALL($1::bigint[])) AS members,
               (SELECT count(*) FROM extracted_links el WHERE el.group_id = g.id AND el.id != ALL($2::bigint[])) AS links
        FROM groups g
        LEFT JOIN group_members gm ON gm.group_id = g.id
        WHERE g.id != ALL($3::bigint[])
        GROUP BY g.id
        ORDER BY members DESC
        """,
        bl.member_ids, bl.link_ids, bl.group_ids,
    )
    for r in rows:
        if kind is not None and r["kind"] != kind:
            continue
        if (extract_username(r["username"], r["invite_input"]) or "").lower() == target:
            return r
    return None


async def find_group_by_chat_id(pool: asyncpg.Pool, tg_chat_id: int) -> asyncpg.Record | None:
    """One group by its real Telegram chat id (often NULL for CSV-imported groups)."""
    return await pool.fetchrow(
        "SELECT id, title, username, invite_input, tg_chat_id, kind FROM groups WHERE tg_chat_id = $1", tg_chat_id
    )


async def find_group_by_invite_hash(pool: asyncpg.Pool, invite_hash: str) -> asyncpg.Record | None:
    """A private group/channel by the hash of its t.me/+HASH invite link (stored in invite_input).
    The way to recognise a private group with no public username and no tg_chat_id (both often NULL
    for CSV-imported groups) - used to resolve/match an invite link against the archive. Returns the
    member/link counts too (like find_group_by_exact_username) so the card shows the right totals.
    strpos (literal case-insensitive substring), not ILIKE: an invite hash can contain '_'/'-', which
    would be wildcards in ILIKE and could false-match a different group."""
    if not invite_hash:
        return None
    bl = await resolve_blacklist(pool)
    return await pool.fetchrow(
        """
        SELECT g.id, g.title, g.username, g.invite_input, g.tg_chat_id, g.kind,
               count(DISTINCT gm.member_id) FILTER (WHERE gm.member_id != ALL($1::bigint[])) AS members,
               (SELECT count(*) FROM extracted_links el WHERE el.group_id = g.id AND el.id != ALL($2::bigint[])) AS links
        FROM groups g
        LEFT JOIN group_members gm ON gm.group_id = g.id
        WHERE strpos(lower(g.invite_input), lower($4)) > 0
          AND g.id != ALL($3::bigint[])
        GROUP BY g.id
        ORDER BY members DESC
        LIMIT 1
        """,
        bl.member_ids, bl.link_ids, bl.group_ids, invite_hash,
    )


async def get_group_by_id(pool: asyncpg.Pool, group_id: int) -> asyncpg.Record | None:
    """Re-fetch a group by its id, used by the members-list pagination callback (which only carries the
    id, not the original query)."""
    return await pool.fetchrow(
        "SELECT id, title, username, invite_input FROM groups WHERE id = $1", group_id
    )


async def list_groups_with_counts(pool: asyncpg.Pool, kind: str = "group") -> list[asyncpg.Record]:
    """Scraped entities of one kind ('group' — groups & supergroups; 'channel' — broadcast
    channels) with member and extracted-link counts. Blacklisted groups are dropped and their
    blacklisted members/links excluded from the counts, so nothing blacklisted shows or is counted."""
    bl = await resolve_blacklist(pool)
    return await pool.fetch(
        """
        SELECT g.id, g.title, g.username, g.invite_input, g.kind,
               count(DISTINCT gm.member_id) FILTER (WHERE gm.member_id != ALL($2::bigint[])) AS members,
               (SELECT count(*) FROM extracted_links el WHERE el.group_id = g.id AND el.id != ALL($3::bigint[])) AS links
        FROM groups g
        LEFT JOIN group_members gm ON gm.group_id = g.id
        WHERE g.kind = $1
          AND g.id != ALL($4::bigint[])
        GROUP BY g.id
        ORDER BY lower(g.title)
        """,
        kind, bl.member_ids, bl.link_ids, bl.group_ids,
    )


async def find_or_create_legacy_group(pool: asyncpg.Pool, *, invite_input: str, title: str) -> int:
    """Used by the member CSV import. CSVs have no numeric tg_chat_id, so the group is identified by
    canonical identity across all existing groups."""
    target = canonical_group_key(title, None, invite_input)

    existing = await pool.fetch("SELECT id, title, username, invite_input FROM groups")
    for row in existing:
        if canonical_group_key(row["title"], row["username"], row["invite_input"]) == target:
            # Having members proves it's a group, so clear any earlier 'channel' classification.
            await pool.execute("UPDATE groups SET kind = 'group' WHERE id = $1 AND kind <> 'group'", row["id"])
            return row["id"]

    return await pool.fetchval(
        """
        INSERT INTO groups (tg_chat_id, title, invite_input, username, is_public)
        VALUES (NULL, $1, $2, NULL, true)
        RETURNING id
        """,
        title, invite_input,
    )


async def find_or_create_group_by_title(pool: asyncpg.Pool, *, title: str, invite_input: str, kind: str = "group") -> int:
    """Resolve the group for a links CSV by its TITLE - the filename that member and links CSVs of the
    same group share. An old links CSV may lack the username the member CSV had (so their canonical
    keys differ); matching by title attaches the links to the existing member group instead of
    splitting off a duplicate. Creates a links-only group only when no group has that title yet.
    kind ('group'/'channel') is applied, but never labels a group that has members as a channel."""
    target = (title or "").strip().lower()
    existing = await pool.fetch("SELECT id, title, username, invite_input FROM groups")
    for row in existing:
        if (row["title"] or "").strip().lower() == target:
            # Upgrade the group's invite_input if it currently has no usable link but this CSV does
            # (e.g. an old links CSV made a title-only group; a re-scrape now carries a real handle),
            # so the group name becomes clickable in the group lists.
            if group_link(row["username"], row["invite_input"]) is None and group_link(None, invite_input) is not None:
                await pool.execute("UPDATE groups SET invite_input = $2 WHERE id = $1", row["id"], invite_input)
            await pool.execute(
                "UPDATE groups SET kind = $2 WHERE id = $1 "
                "AND NOT EXISTS (SELECT 1 FROM group_members WHERE group_id = $1)",
                row["id"], kind,
            )
            return row["id"]

    return await pool.fetchval(
        """
        INSERT INTO groups (tg_chat_id, title, invite_input, username, kind, is_public)
        VALUES (NULL, $1, $2, NULL, $3, true)
        RETURNING id
        """,
        title, invite_input, kind,
    )


async def merge_duplicate_groups(pool: asyncpg.Pool) -> int:
    """Consolidate duplicate groups into one, moving relations to the survivor. Two group rows are
    treated as the same group if they share a canonical key (same link) OR the same title - the title
    catches the case where a member CSV carried the username but an old links CSV didn't, which would
    otherwise leave the links on a separate title-keyed duplicate. Returns how many were merged."""
    rows = await pool.fetch("SELECT id, title, username, invite_input, tg_chat_id, kind FROM groups")

    # Union-find: union groups that share a canonical key or a (lowercased) title.
    parent = {r["id"]: r["id"] for r in rows}

    def find(x: int) -> int:
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    first_with_key: dict[str, int] = {}
    for r in rows:
        keys = (
            canonical_group_key(r["title"], r["username"], r["invite_input"]),
            (r["title"] or "").strip().lower(),
        )
        for key in keys:
            if key in first_with_key:
                union(r["id"], first_with_key[key])
            else:
                first_with_key[key] = r["id"]

    classes: dict[int, list[asyncpg.Record]] = {}
    for r in rows:
        classes.setdefault(find(r["id"]), []).append(r)

    merged = 0
    for group in classes.values():
        if len(group) < 2:
            continue

        # Survivor: a real tg_chat_id first, then one that has a public link (keeps the richer
        # identity, e.g. the member group's username over a title-only links group), then the oldest.
        group.sort(key=lambda r: (r["tg_chat_id"] is None, group_link(r["username"], r["invite_input"]) is None, r["id"]))
        survivor, *duplicates = group

        for dup in duplicates:
            for table, key_columns in (
                ("group_members", "member_id, source"),
                ("extracted_links", "link_key"),
            ):
                condition = " AND ".join(f"c.{col.strip()} = d.{col.strip()}" for col in key_columns.split(","))
                await pool.execute(
                    f"""
                    DELETE FROM {table} d
                    WHERE d.group_id = $1 AND EXISTS (
                        SELECT 1 FROM {table} c
                        WHERE c.group_id = $2 AND {condition}
                    )
                    """,
                    dup["id"], survivor["id"],
                )
                await pool.execute(f"UPDATE {table} SET group_id = $1 WHERE group_id = $2", survivor["id"], dup["id"])

            await pool.execute("DELETE FROM groups WHERE id = $1", dup["id"])
            merged += 1

        # The merged entity is a channel only if every row was a channel and it ended up with no
        # members; any 'group' row (or any member) makes the survivor a group.
        any_group = any(r["kind"] != "channel" for r in group)
        has_members = await pool.fetchval("SELECT EXISTS (SELECT 1 FROM group_members WHERE group_id = $1)", survivor["id"])
        survivor_kind = "group" if (any_group or has_members) else "channel"
        await pool.execute("UPDATE groups SET kind = $2 WHERE id = $1", survivor["id"], survivor_kind)

    return merged
