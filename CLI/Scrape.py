import csv
import asyncio
from pathlib import Path

from telethon.errors import FloodWaitError

from collectors.entitykind import GROUP, classify_entity, entity_display, entity_kind_label, entity_username
from collectors.csv_merge import existing_member_users
from collectors.naming import safe_group_filename
from collectors.resolve import NotAMemberError, resolve_entity
from collectors.retry import MAX_RETRIES, run_with_retry
from collectors.scrape_errors import EMPTY, NOT_FOUND, NOT_MEMBER, RATE_LIMITED, WRONG_TYPE, ScrapeError
from collectors.throttle import PARTICIPANTS_SLEEP_EVERY, page_sleep_seconds

NO_USERNAME = "(No Username)"


async def extract_members(client, group_input):
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

    # Members come only from groups/supergroups; a broadcast channel has none to list (a user neither).
    if classify_entity(group) != GROUP:
        print(f"❌ This is a {entity_kind_label(group)} — scrape members only from groups/supergroups (use Scrape Links for a channel).")
        raise ScrapeError(WRONG_TYPE, detail=entity_kind_label(group))

    safe_name = safe_group_filename(group.title, group.id)
    output_file = Path("output") / "Members From Groups" / f"{safe_name}.csv"
    output_file.parent.mkdir(parents=True, exist_ok=True)

    print("\n📊 Extracting...")

    participants_holder = {}
    attempt_count = 0

    async def attempt():
        nonlocal attempt_count
        attempt_count += 1
        print(f"🔄 Attempt ({attempt_count}/{MAX_RETRIES})...")
        # Iterate instead of one get_participants() call so we can pace ourselves on big groups,
        # like the message/link scrapers do. Telethon still paginates underneath; the periodic
        # sleep just spreads the requests out to stay under the radar.
        collected = []
        async for participant in client.iter_participants(group):
            collected.append(participant)
            if len(collected) % PARTICIPANTS_SLEEP_EVERY == 0:
                print(f"   👥 Participants read: {len(collected)}")
                await asyncio.sleep(page_sleep_seconds())
        participants_holder["value"] = collected

    ok = await run_with_retry(attempt)
    if not ok:
        raise ScrapeError(RATE_LIMITED)
    participants = participants_holder.get("value")
    if not participants:
        print("❌ NO MEMBERS EXTRACTED")
        raise ScrapeError(EMPTY)

    scraped = {}
    for p in participants:
        scraped.setdefault(str(p.id), entity_username(p) or NO_USERNAME)

    # Additive: keep everyone already in the CSV, add only new members. A re-scrape never drops data.
    users = existing_member_users(output_file, NO_USERNAME)
    new_added = sum(1 for uid in scraped if uid not in users)
    for uid, uname in scraped.items():
        users.setdefault(uid, uname)

    total_members = len(users)
    with_username = sum(1 for u in users.values() if u != NO_USERNAME)
    without_username = total_members - with_username
    print(f"   ➕ New this run: {new_added}")

    data = [{"Invite_link": group_input, "Username": uname, "User_id": uid} for uid, uname in users.items()]

    print("\n📌 SUMMARY:")
    print(f"👥 Total members: {total_members}")
    print(f"✅ With username: {with_username}")
    print(f"❌ Without username: {without_username}")

    print("\n💾 Saving...")

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Invite_link", "Username", "User_id"])
        writer.writeheader()
        writer.writerows(data)

    print(f"✅ Done! Saved to: {output_file}")

    return {
        "output_file": output_file,
        "group_title": group.title,
        "total": total_members,
        "new_added": new_added,
        "with_username": with_username,
        "without_username": without_username,
    }
