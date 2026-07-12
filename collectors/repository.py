import asyncpg

from db.queries import groups as groups_q
from db.queries import links as links_q
from db.queries import members as members_q


async def save_legacy_csv_import(
    pool: asyncpg.Pool,
    *,
    invite_input: str,
    title: str,
    members: dict[str, str],
    source: str,
) -> int:
    """CSV import (the only DB writer). No real tg_chat_id, so the group is identified by
    invite_input/title canonical identity."""
    group_id = await groups_q.find_or_create_legacy_group(pool, invite_input=invite_input, title=title)

    saved = 0
    for uid_str, username in members.items():
        uname = None if username in (None, "", "(No Username)") else username
        member_id = await members_q.upsert_member(pool, tg_user_id=int(uid_str), username=uname)
        await members_q.link_group_member(pool, group_id=group_id, member_id=member_id, source=source)
        saved += 1

    return saved


async def save_links_import(
    pool: asyncpg.Pool,
    *,
    invite_input: str,
    title: str,
    kind: str = "group",
    links: list[dict],
) -> int:
    """Import an extracted-links CSV. Attaches the links to the group with the same title (what member
    and links CSVs share), so a group's links and members point at one group entity even when an old links CSV
    lacks the username the member CSV had. kind ('group'/'channel') is the scraped source type."""
    group_id = await groups_q.find_or_create_group_by_title(pool, title=title, invite_input=invite_input, kind=kind)

    saved = 0
    for row in links:
        await links_q.insert_link(
            pool,
            group_id=group_id,
            link=row["link"],
            sender_user_id=row["sender_user_id"],
            sender_username=row["sender_username"],
            message_date=row["message_date"],
        )
        saved += 1

    return saved
