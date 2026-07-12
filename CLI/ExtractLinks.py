import csv
import re
import asyncio
from pathlib import Path
from datetime import timezone, timedelta
from telethon.errors import FloodWaitError
from telethon.tl.types import MessageEntityTextUrl, MessageEntityMention

from bot.group_links import link_key, normalize_entity_link
from collectors.csv_merge import existing_link_rows
from collectors.entitykind import CHANNEL, classify_entity, entity_display, entity_kind_label, entity_username
from collectors.naming import safe_group_filename
from collectors.resolve import NotAMemberError, resolve_entity
from collectors.scrape_errors import EMPTY, NOT_FOUND, NOT_MEMBER, RATE_LIMITED, ScrapeError
from collectors.retry import run_with_retry
from collectors.throttle import page_sleep_seconds

DEFAULT_LIMIT = 500
MAX_LIMIT = 5000

OUTPUT_DIR = Path("output/Extracted Links")

# Timezone applied to message timestamps (UTC+2).
TIMEZONE = timezone(timedelta(hours=2))

# Matches any t.me/ or telegram.me/ link. The lookbehind avoids false positives on domains that
# happen to end with "t.me"/"telegram.me" (e.g. about.me) but aren't Telegram.
LINK_PATTERN = re.compile(
    r"(?<![\w.])(?:https?://)?(?:t\.me|telegram\.me)/[\w+/]+",
    re.IGNORECASE
)


def normalize_link(link):
    """Add https:// if missing."""
    if not link.startswith("http"):
        return "https://" + link
    return link


def extract_links_from_message(message):
    """Find Telegram links in the text, behind clickable text, and behind @username mentions."""
    found = set()

    for match in LINK_PATTERN.findall(message.text or ""):
        found.add(normalize_link(match))

    for entity, text in message.get_entities_text():
        if isinstance(entity, MessageEntityTextUrl):
            if LINK_PATTERN.search(entity.url):
                found.add(normalize_link(entity.url))
        elif isinstance(entity, MessageEntityMention):
            found.add(normalize_link(f"t.me/{text.lstrip('@')}"))

    return found


def extract_forward_link(message):
    """If the message is forwarded from a public channel/group whose entity is already known from the
    same history batch, return the link to it. Deliberately does NOT call get_chat(): resolving
    uncached forward sources one-by-one inside the message loop is the easiest way to trigger a
    FloodWait, so we accept missing the occasional forward link in exchange for not hammering the API."""
    fwd = message.forward
    if not fwd:
        return None

    chat = fwd.chat
    if chat is None:
        return None

    username = getattr(chat, "username", None)
    if not username:
        return None

    link = f"t.me/{username}"
    if fwd.channel_post:
        link += f"/{fwd.channel_post}"
    return normalize_link(link)


async def extract_links(client, group_input, limit):
    try:
        print(f"\n🔍 Looking up: {group_input}")
        group = await resolve_entity(client, group_input)
        print(f"✅ FOUND ({entity_kind_label(group)}): {entity_display(group)}")
    except NotAMemberError:
        print("🔒 Private group/channel the scraping account hasn't joined — join it first, then scrape.")
        raise ScrapeError(NOT_MEMBER)
    except FloodWaitError as e:
        print("⏳ Telegram rate-limit (FloodWait) while resolving — try again later.")
        raise ScrapeError(RATE_LIMITED, detail=str(getattr(e, "seconds", 0) or 0))
    except Exception as e:
        print(f"❌ NOT FOUND: {e}")
        raise ScrapeError(NOT_FOUND) from e

    # Links can come from a broadcast channel, not only a group.
    source_kind = CHANNEL if classify_entity(group) == CHANNEL else "group"

    safe_name = safe_group_filename(group.title, group.id)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / f"{safe_name}_links.csv"

    print(f"\n📨 Reading last {limit} messages...")

    # The scraped entity's own link: don't archive a group's/channel's link to ITSELF.
    own_link = normalize_entity_link(f"t.me/{entity_username(group)}") if entity_username(group) else None

    # Additive: keep the links already in the CSV, and pre-load their keys so the scrape skips them.
    existing_rows, existing_keys = existing_link_rows(output_file, link_key)

    results = []
    messages_read = 0
    links_found = 0
    links_saved = 0
    links_dup = 0
    seen_links = set(existing_keys)

    async def attempt():
        nonlocal messages_read, links_found, links_saved, links_dup

        async for message in client.iter_messages(group, limit=limit):
            messages_read += 1

            links = extract_links_from_message(message) if message.text else set()

            forward_link = extract_forward_link(message)
            if forward_link:
                links.add(forward_link)

            if not links:
                continue

            uid = str(message.sender_id) if message.sender_id else "(Unknown)"
            username = entity_username(message.sender) or "(None)" if message.sender else "(None)"

            date = message.date.astimezone(TIMEZONE).strftime("%Y-%m-%d %H:%M") if message.date else ""

            for raw in links:
                # Keep only links to a user/channel/group, reduced to the entity (message ids/queries
                # stripped); drop service links and the scraped entity's own link. See normalize_entity_link.
                link = normalize_entity_link(raw)
                if link is None or (own_link and link.lower() == own_link.lower()):
                    continue
                links_found += 1
                key = link_key(link)
                if key in seen_links:
                    links_dup += 1
                    continue
                seen_links.add(key)
                links_saved += 1
                results.append({"Invite_link": group_input, "Link": link, "User_id": uid, "Username": username, "Date": date, "Kind": source_kind})

            if messages_read % 100 == 0:
                print(f"   📩 Messages: {messages_read} | Links found: {links_found}")
                await asyncio.sleep(page_sleep_seconds())

    ok = await run_with_retry(attempt)

    print("\n📌 SUMMARY:")
    print(f"📨 Messages read : {messages_read}")
    print(f"🔗 Links found   : {links_found}")
    print(f"💾 Links saved   : {links_saved}")
    print(f"♻️  Duplicate links : {links_dup}")

    all_rows = existing_rows + results  # existing links kept + new ones appended
    if not all_rows:
        print("❌ NO LINKS FOUND")
        raise ScrapeError(RATE_LIMITED if not ok else EMPTY)

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Invite_link", "Link", "User_id", "Username", "Date", "Kind"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"✅ Done! Saved to: {output_file}")
    print("ℹ️  Imported into the database as soon as the bot notices it (browse it from the bot's Browse, or the CLI's groups/channels).")

    return {
        "output_file": output_file,
        "group_title": group.title,
        "messages_read": messages_read,
        "links_found": links_found,
        "links_saved": links_saved,
        "links_dup": links_dup,
    }
