import csv
import asyncio
from pathlib import Path

from telethon.errors import FloodWaitError

from collectors.csv_merge import existing_member_users
from collectors.entitykind import GROUP, classify_entity, entity_display, entity_kind_label, entity_username
from collectors.naming import safe_group_filename
from collectors.resolve import NotAMemberError, resolve_entity
from collectors.retry import run_with_retry
from collectors.scrape_errors import EMPTY, NOT_FOUND, NOT_MEMBER, RATE_LIMITED, WRONG_TYPE, ScrapeError
from collectors.throttle import page_sleep_seconds

DEFAULT_LIMIT = 500
MAX_LIMIT = 5000
NO_USERNAME = "(No Username)"


async def scrape_from_messages(client, group_input, limit):
    try:
        print(f"\n🔍 Looking up group: {group_input}")
        group = await resolve_entity(client, group_input)
        print(f"✅ FOUND ({entity_kind_label(group)}): {entity_display(group)}")
    except NotAMemberError:
        print("🔒 Private group the scraping account hasn't joined — join it first, then scrape.")
        raise ScrapeError(NOT_MEMBER)
    except FloodWaitError as e:
        print("⏳ Telegram rate-limit (FloodWait) while resolving — try again later.")
        raise ScrapeError(RATE_LIMITED, detail=str(getattr(e, "seconds", 0) or 0))
    except Exception as e:
        print(f"❌ NOT FOUND: {e}")
        raise ScrapeError(NOT_FOUND) from e

    # Message senders are meaningful only in groups/supergroups; a broadcast channel posts as itself.
    if classify_entity(group) != GROUP:
        print(f"❌ This is a {entity_kind_label(group)} — scrape message senders only from groups/supergroups (use Scrape Links for a channel).")
        raise ScrapeError(WRONG_TYPE, detail=entity_kind_label(group))

    safe_name = safe_group_filename(group.title, group.id)
    output_file = Path("output") / "Members From Messages" / f"{safe_name}.csv"
    output_file.parent.mkdir(parents=True, exist_ok=True)

    print(f"\n📨 Reading last {limit} messages...")

    users = {}
    messages_read = 0

    async def attempt():
        nonlocal messages_read
        async for message in client.iter_messages(group, limit=limit):
            messages_read += 1

            if message.sender_id is None:
                continue

            uid = str(message.sender_id)
            if uid in users:
                continue

            username = NO_USERNAME
            if message.sender:
                username = entity_username(message.sender) or NO_USERNAME

            users[uid] = username

            if messages_read % 100 == 0:
                print(f"   📩 Messages read: {messages_read} | Unique users: {len(users)}")
                await asyncio.sleep(page_sleep_seconds())

    ok = await run_with_retry(attempt)

    if not users:
        print("❌ NO USERS FOUND")
        raise ScrapeError(RATE_LIMITED if not ok else EMPTY)

    # Additive: keep everyone already in the CSV, add only new senders. A re-scrape never drops data.
    scraped = users
    users = existing_member_users(output_file, NO_USERNAME)
    new_added = sum(1 for uid in scraped if uid not in users)
    for uid, uname in scraped.items():
        users.setdefault(uid, uname)
    print(f"   ➕ New this run: {new_added}")

    with_username = sum(1 for u in users.values() if u != NO_USERNAME)
    without_username = len(users) - with_username

    print("\n📌 SUMMARY:")
    print(f"📨 Messages read : {messages_read}")
    print(f"👥 Unique users  : {len(users)}")
    print(f"✅ With username : {with_username}")
    print(f"❌ Without username : {without_username}")

    print("\n💾 Saving...")

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Invite_link", "Username", "User_id"])
        writer.writeheader()
        for uid, uname in users.items():
            writer.writerow({"Invite_link": group_input, "Username": uname, "User_id": uid})

    print(f"✅ Done! Saved to: {output_file}")

    return {
        "output_file": output_file,
        "group_title": group.title,
        "messages_read": messages_read,
        "total": len(users),
        "new_added": new_added,
        "with_username": with_username,
        "without_username": without_username,
    }
