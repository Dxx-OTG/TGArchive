"""Command handlers for the DB-backed CLI REPL (CLI/Menu.py).

Mirrors the Telegram bot command-for-command and reuses the exact same query/logic layer
(db.queries, db.blacklist, bot.group_links, bot.querykind, bot.favorites), rendered as plain text
for the terminal instead of Telegram HTML + inline keyboards. The CLI reads the same PostgreSQL the
bot does; CLI/Menu.py syncs the CSVs into it on startup and after every scrape, so both see the same
data. Every handler is `async def cmd_x(ctx, arg)` and prints directly.
"""
import csv
import zipfile
from pathlib import Path

from telethon.errors import FloodWaitError

from bot import favorites_store
from bot.entitykind import BOT, CHANNEL, GROUP, USER
from bot.favorites import RateLimited, TelegramLookupUnavailable, parse_favorite_arg, resolve_target
from bot.group_links import canonical_group_key, dedupe_groups, group_link
from bot.i18n import plural
from bot.querykind import QueryKind, classify_query
from db.blacklist import is_favorite_blacklisted
from db.queries import groups as groups_q
from db.queries import links as links_q
from db.queries import members as members_q
from collectors.check import (
    STATUS_OK,
    age_text,
    build_link_view,
    build_view,
    check_and_store,
    gather_link_targets,
    gather_targets,
    is_dead,
    load_status,
    remove_inactive,
    remove_inactive_links,
    run_check_all,
    sort_targets,
    status_glyph,
)
from collectors.csv_import import find_group_csv_files, remove_registered_member, write_registered, write_registered_member
from bot import card as card_mod

from CLI.ExtractLinks import DEFAULT_LIMIT as LINKS_DEFAULT_LIMIT, MAX_LIMIT as LINKS_MAX_LIMIT, extract_links
from CLI.Messages import DEFAULT_LIMIT as MSG_DEFAULT_LIMIT, MAX_LIMIT as MSG_MAX_LIMIT, scrape_from_messages
from CLI.Scrape import extract_members

OUTPUT_DIR = Path("output")
FAVORITES_DIR = OUTPUT_DIR / "Favorites"
EXPORT_DIR = Path("exports")

# Long terminal listings are capped (the bot paginates instead); use export to get everything.
LIST_CAP = 200
REMOVE_WORDS = {"remove", "rm", "del", "delete"}


# --- plain-text rendering helpers ---------------------------------------------------------------

def _counted(n: int, one: str, many: str) -> str:
    return f"{n} {plural(n, one, many)}"


def _group_name(title: str, username: str | None, invite_input: str | None) -> str:
    link = group_link(username, invite_input)
    return f"{title}  ({link})" if link else title


def _group_line(g) -> str:
    icon = "📢" if (g.get("kind") == "channel" and not g["members"]) else "📁"
    counts = []
    if g["members"]:
        counts.append(f"👥 {g['members']}")
    if g["links"]:
        counts.append(f"🔗 {g['links']}")
    line = f"{icon} {_group_name(g['title'], g['username'], g['invite_input'])}"
    if counts:
        line += "  — " + " · ".join(counts)
    return line


def _print_capped(rows: list, render, cap: int = LIST_CAP) -> None:
    for r in rows[:cap]:
        print(render(r))
    if len(rows) > cap:
        print(f"   …and {len(rows) - cap} more — use export to get them all.")


def _print_links_grouped(rows: list, *, cap: int = LIST_CAP) -> None:
    """Print links grouped by source channel/group (alphabetical), then link — the CLI mirror of the
    bot's grouped link lists. Each link shows 👤 N = how many people shared it (by link_key). rows
    carry group_title/group_kind/sharers and are pre-sorted. Only links count toward the cap."""
    prev = object()
    for i, r in enumerate(rows):
        if i >= cap:
            print(f"   …and {len(rows) - cap} more — use export to get them all.")
            break
        title = r["group_title"] or "?"
        if title != prev:
            prev = title
            icon = "📢" if r["group_kind"] == "channel" else "📁"
            print(f"{icon} {title}")
        n = r["sharers"] if "sharers" in r.keys() else 0
        line = f"   • {r['link']}"
        if n:
            line += f" — 👤 {n}"
        print(line)


# --- stats -------------------------------------------------------------------------------------

async def _stats_members(ctx, which: str) -> None:
    rows = await members_q.list_members(ctx.bot_pool, which)  # blacklisted excluded in the query
    bots = which == "bots"
    label = {"all": "All Users", "with": "Users With Username", "without": "Users Without Username", "bots": "All Bots"}[which]
    if not rows:
        print(f"No {'bots' if bots else 'users'} ({label}).")
        return
    print(f"{'🤖' if bots else '👤'} {label} — {_counted(len(rows), 'Bot' if bots else 'User', 'Bots' if bots else 'Users')}")
    _print_capped(rows, lambda r: f"   • @{r['username']} — {r['tg_user_id']}" if r["username"] else f"   • (no username) — {r['tg_user_id']}")


async def _stats_links(ctx) -> None:
    rows = await links_q.list_all_links(ctx.bot_pool)
    if not rows:
        print("No links in the database.")
        return
    print(f"🔗 All Links — {_counted(len(rows), 'Link', 'Links')}")
    _print_links_grouped(rows)


async def cmd_stats(ctx, arg: str) -> None:
    # 'stats <element>' lists them all — the CLI mirror of the bot's tappable Stats counts.
    el = arg.strip().lower()
    if el == "groups":
        return await cmd_groups(ctx, "")
    if el == "channels":
        return await cmd_channels(ctx, "")
    if el in ("members", "users"):
        return await _stats_members(ctx, "all")
    if el in ("withusername", "with"):
        return await _stats_members(ctx, "with")
    if el in ("nousername", "without"):
        return await _stats_members(ctx, "without")
    if el == "bots":
        return await _stats_members(ctx, "bots")
    if el == "links":
        return await _stats_links(ctx)
    if el:
        print("❓ Unknown element. Try: stats groups | channels | users | bots | withusername | nousername | links")
        return

    row = await ctx.bot_pool.fetchrow(
        "SELECT (SELECT count(*) FROM groups WHERE kind = 'group') AS groups,"
        " (SELECT count(*) FROM groups WHERE kind = 'channel') AS channels,"
        " (SELECT count(*) FROM extracted_links) AS links"
    )
    counts = await members_q.count_members_by_kind(ctx.bot_pool)  # members split into users vs bots
    print("📊 Database — 'stats <element>' lists them all:")
    print(f"Groups: {row['groups']}   (stats groups)")
    print(f"Channels: {row['channels']}   (stats channels)")
    print(f"🔗 Links: {row['links']}   (stats links)")
    print(f"👤 Users: {counts['users']}   (stats users)")
    print(f"✅ With Username: {counts['with_username']}   (stats withusername)")
    print(f"❌ Without Username: {counts['without_username']}   (stats nousername)")
    print(f"🤖 Bots: {counts['bots']}   (stats bots)")


# --- groups, channels -------------------------------------------------------------------------

async def _load_groups(ctx, kind: str) -> list:
    rows = await groups_q.list_groups_with_counts(ctx.bot_pool, kind)  # blacklisted excluded in the query
    return dedupe_groups(rows, link_fn=lambda r: group_link(r["username"], r["invite_input"]), score_fn=lambda r: r["members"])


async def cmd_groups(ctx, arg: str) -> None:
    items = await _load_groups(ctx, "group")
    if not items:
        print("No groups yet — scrape a group first (scrapemembers / scrapemessages).")
        return
    print(f"🗂 {_counted(len(items), 'Scraped Group', 'Scraped Groups')}")
    print("👥 Users · 🔗 Links")
    _print_capped(items, _group_line)


async def cmd_channels(ctx, arg: str) -> None:
    items = await _load_groups(ctx, "channel")
    if not items:
        print("No channels yet — run scrapelinks on a channel first.")
        return
    print(f"📢 {_counted(len(items), 'Scraped Channel', 'Scraped Channels')}")
    print("🔗 Links")
    _print_capped(items, _group_line)


def _person_line(p, icon: str = "👤") -> str:
    who = f"@{p['username']}" if p["username"] else f"#{p['tg_user_id']}"
    text = f"{icon} {who} · {_counted(p['num_groups'], 'Group', 'Groups')}"
    if p["num_links"]:
        text += f" · {_counted(p['num_links'], 'Link', 'Links')}"
    return text


async def _list_people(ctx, *, bots: bool) -> None:
    """All users (bots=False) or bots (bots=True) with their group/link counts - mirror of Browse."""
    people = await members_q.list_people(ctx.bot_pool, bots=bots)
    icon = "🤖" if bots else "👤"
    if not people:
        print("No bots yet — bots turn up while scraping members/senders." if bots else "No users yet — scrape a group's members first.")
        return
    print(f"{icon} {_counted(len(people), 'Bot' if bots else 'User', 'Bots' if bots else 'Users')}")
    print("📁 Groups · 🔗 Links")
    _print_capped(people, lambda p: _person_line(p, icon))
    print(f"Open one with: {'searchbots' if bots else 'searchusers'} <@username|id>")


async def cmd_users(ctx, arg: str) -> None:
    await _list_people(ctx, bots=False)


async def cmd_bots(ctx, arg: str) -> None:
    await _list_people(ctx, bots=True)


# --- searchgroups, searchchannels -------------------------------------------------------------

async def _search_groups(ctx, query: str, db_kind: str) -> None:
    kind, value = classify_query(query)

    if kind is QueryKind.USERNAME:
        # find_group_by_exact_username already excludes blacklisted groups (returns None).
        group = await groups_q.find_group_by_exact_username(ctx.bot_pool, value, kind=db_kind)
        if group is None:
            print(f"❌ Nothing for '{query}'.")
            return
        print(f"✅ 1 Result for '{query}':")
        print(_group_line(group))
        return

    rows = await groups_q.search_groups_by_name(ctx.bot_pool, query, db_kind)
    groups = dedupe_groups(rows, link_fn=lambda r: group_link(r["username"], r["invite_input"]), score_fn=lambda r: r["members"])
    if not groups:
        print(f"❌ Nothing for '{query}'.")
        return
    print(f"✅ {_counted(len(groups), 'Result', 'Results')} for '{query}':")
    _print_capped(groups, _group_line)


async def cmd_searchgroups(ctx, arg: str) -> None:
    if not arg:
        print("Usage: searchgroups <group>")
        return
    await _search_groups(ctx, arg, "group")


async def cmd_searchchannels(ctx, arg: str) -> None:
    if not arg:
        print("Usage: searchchannels <channel>")
        return
    await _search_groups(ctx, arg, "channel")


async def cmd_searchlinks(ctx, arg: str) -> None:
    """Find shared t.me links whose URL contains the query (mirrors the bot's Search -> Links)."""
    query = arg.strip()
    if not query:
        print("Usage: searchlinks <text>")
        return
    rows = await links_q.search_links(ctx.bot_pool, query)
    if not rows:
        print(f"❌ Nothing for '{query}'.")
        return
    print(f"🔗 {_counted(len(rows), 'Link', 'Links')} for '{query}':")
    _print_links_grouped(rows)


# --- searchusers -------------------------------------------------------------------------------

async def _fetch_people(ctx, raw_query: str, *, bots: bool = False) -> list:
    from bot.entitykind import is_bot_username
    kind, value = classify_query(raw_query)
    if kind is QueryKind.ID:
        rows = await members_q.people_by_id(ctx.bot_pool, int(value))
    elif kind is QueryKind.USERNAME:
        rows = await members_q.people_by_username(ctx.bot_pool, value)
    else:
        return await members_q.search_member_people(ctx.bot_pool, value, bots=bots)
    return [r for r in rows if is_bot_username(r["username"]) == bots]


async def _print_user(ctx, tg_user_id: int) -> bool:
    group_rows = await members_q.find_member_groups(ctx.bot_pool, str(tg_user_id))
    link_rows = await links_q.links_by_user(ctx.bot_pool, tg_user_id)
    if not group_rows and not link_rows:
        return False
    username = group_rows[0]["username"] if group_rows else None
    groups = dedupe_groups(group_rows, link_fn=lambda r: group_link(r["group_username"], r["invite_input"]))

    print("✅ Found")
    print(f"👤 {tg_user_id}")
    print(f"🔖 @{username}" if username else "🔖 Username: none")
    print(f"📁 In {_counted(len(groups), 'Group', 'Groups')}:")
    _print_capped(groups, lambda r: f"   • {_group_name(r['title'], r['group_username'], r['invite_input'])}")
    if link_rows:
        print(f"🔗 {_counted(len(link_rows), 'Link', 'Links')} sent:")
        _print_links_grouped(link_rows)  # grouped by source; 👤 N = how many shared each link
    return True


async def _search_people(ctx, arg: str, *, bots: bool) -> None:
    usage = "searchbots" if bots else "searchusers"
    if not arg:
        print(f"Usage: {usage} <{'bot' if bots else 'user'}>")
        return
    people = await _fetch_people(ctx, arg, bots=bots)
    if not people:
        print(f"❌ Nothing for '{arg}'.")
        return
    if len(people) == 1:
        if not await _print_user(ctx, people[0]["tg_user_id"]):
            print(f"❌ Nothing for '{arg}'.")
        return
    print(f"✅ {_counted(len(people), 'Result', 'Results')} for '{arg}':")
    _print_capped(people, lambda p: _person_line(p, "🤖" if bots else "👤"))
    print(f"Open one with: {usage} <@username|id>")


async def cmd_searchusers(ctx, arg: str) -> None:
    await _search_people(ctx, arg, bots=False)


async def cmd_searchbots(ctx, arg: str) -> None:
    await _search_people(ctx, arg, bots=True)


# --- a group's members / links (the CLI stand-in for the bot's tappable counts) -----------------

async def cmd_members(ctx, arg: str) -> None:
    if not arg:
        print("Usage: members <@username|link>")
        return
    group = await groups_q.find_group_by_exact_username(ctx.bot_pool, arg)
    if group is None:
        print(f"❌ Nothing with username '{arg}'. Use the exact username — see groups / channels.")
        return
    rows = await members_q.list_distinct_group_members(ctx.bot_pool, group["id"])  # blacklisted excluded
    if not rows:
        print(f"No members for '{group['title']}'.")
        return
    print(f"👥 {_group_name(group['title'], group['username'], group['invite_input'])} — {_counted(len(rows), 'Member', 'Members')}")
    _print_capped(rows, lambda r: f"   • @{r['username']} — {r['tg_user_id']}" if r["username"] else f"   • (no username) — {r['tg_user_id']}")


async def cmd_links(ctx, arg: str) -> None:
    if not arg:
        print("Usage: links <@username|link>")
        return
    group = await groups_q.find_group_by_exact_username(ctx.bot_pool, arg)
    if group is None:
        print(f"❌ Nothing with username '{arg}'. Use the exact username — see groups / channels.")
        return
    rows = await links_q.links_for_group(ctx.bot_pool, group["id"])
    if not rows:
        print(f"No links for '{group['title']}'.")
        return
    print(f"🔗 {_group_name(group['title'], group['username'], group['invite_input'])} — {_counted(len(rows), 'Link', 'Links')}")
    _print_capped(rows, lambda r: f"   • {r['link']}" + (f" — @{r['sender_username']}" if r["sender_username"] else ""))


# --- export ------------------------------------------------------------------------------------

def _output_csvs(*, include_favorites: bool) -> list[Path]:
    if not OUTPUT_DIR.exists():
        return []
    files = sorted(OUTPUT_DIR.rglob("*.csv"))
    if not include_favorites:
        fav = FAVORITES_DIR.resolve()
        files = [f for f in files if fav not in f.resolve().parents]
    return files


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


async def cmd_export(ctx, arg: str) -> None:
    if arg.lower() == "all":
        files = _output_csvs(include_favorites=True)
        if not files:
            print("Nothing to export — output is empty.")
            return
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        zip_path = EXPORT_DIR / "tgarchive_output.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for file in files:
                archive.write(file, file.relative_to(OUTPUT_DIR))
        print(f"📦 Full Archive — {_counted(len(files), 'File', 'Files')} → {zip_path}")
        return
    if not arg:
        print("Usage: export <username> — or export all for the whole archive (zip).")
        return

    group = await groups_q.find_group_by_exact_username(ctx.bot_pool, arg)
    if group is None:
        print(f"❌ Nothing with username '{arg}'. Use the exact username — see groups / channels.")
        return
    members = await members_q.list_group_members(ctx.bot_pool, group["id"])
    links = await links_q.links_for_group(ctx.bot_pool, group["id"])
    if not members and not links:
        print(f"Found '{arg}', but nothing saved for it.")
        return

    title = group["title"]
    if members:
        path = EXPORT_DIR / f"{title}.csv"
        _write_csv(path, ["User_id", "Username", "Source"], [[r["tg_user_id"], r["username"] or "", r["source"]] for r in members])
        print(f"📦 {title} — {_counted(len(members), 'Member', 'Members')} → {path}")
    if links:
        path = EXPORT_DIR / f"{title}_links.csv"
        _write_csv(path, ["Link", "Username", "Date"],
                   [[r["link"], r["sender_username"] or "", f"{r['message_date']:%Y-%m-%d %H:%M}" if r["message_date"] else ""] for r in links])
        print(f"🔗 {title} — {_counted(len(links), 'Link', 'Links')} → {path}")


# --- delete ------------------------------------------------------------------------------------

def _unlink_all(files: list[Path]) -> int:
    deleted = 0
    for file in files:
        try:
            file.unlink()
            deleted += 1
        except OSError as e:
            print(f"⚠️ couldn't remove {file}: {e}")
    return deleted


async def cmd_delete(ctx, arg: str) -> None:
    if arg.lower() == "all":
        files = _output_csvs(include_favorites=False)
        if not files:
            print("Nothing to delete — output is already empty.")
            return
        print(f"⚠️ This deletes ALL scraped CSVs ({_counted(len(files), 'File', 'Files')}) — favorites are kept. Can't be undone.")
        if input("Type 'yes' to confirm: ").strip().lower() != "yes":
            print("Cancelled.")
            return
        n = _unlink_all(files)
        await ctx.resync()
        print(f"🗑 Deleted {_counted(n, 'File', 'Files')}. Archive emptied (favorites kept).")
        return
    if not arg:
        print("Usage: delete <username> — or delete all to wipe everything (favorites kept).")
        return

    group = await groups_q.find_group_by_exact_username(ctx.bot_pool, arg)
    if group is None:
        print(f"❌ Nothing with username '{arg}'. Use the exact username — see groups / channels.")
        return
    canonical = canonical_group_key(group["title"], group["username"], group["invite_input"])
    files = find_group_csv_files(canonical, group["title"], which="all")
    if not files:
        print(f"No CSV files for '{group['title']}'.")
        return
    print(f"🗑 {group['title']} — {_counted(len(files), 'File', 'Files')} to delete (can't be undone):")
    for f in files:
        print(f"   • {f}")
    if input("Type 'yes' to confirm: ").strip().lower() != "yes":
        print("Cancelled.")
        return
    n = _unlink_all(files)
    await ctx.resync()
    print(f"🗑 Deleted {_counted(n, 'File', 'Files')} for '{group['title']}'.")


# --- favorites ---------------------------------------------------------------------------------

def _titled_key(r):
    return (r["title"] or r["username"] or "").lower()


def _fav_target_line(target) -> str:
    if target.kind in (USER, BOT):
        icon = "🤖" if target.kind == BOT else "👤"
        return f"{icon} @{target.username}" if target.username else f"{icon} {target.title or target.tg_id}"
    icon = "📢" if target.kind == CHANNEL else "📂"
    name = target.title or target.username or "?"
    return f"{icon} {name}" + (f"  ({target.link})" if target.link else "")


def _fav_entity_line(r) -> str:
    name = r["title"] or r["username"] or "?"
    return f"   • {name}" + (f"  ({r['link']})" if r["link"] else "")


def _fav_user_line(r) -> str:
    if r["username"]:
        return f"   • @{r['username']}"
    return f"   • {r['title']}" if r["title"] else f"   • {r['tg_id']}"


def _visible_favorites(kind: str) -> list:
    """Saved favorites of one kind, minus any now blacklisted (as if they don't exist)."""
    return [r for r in favorites_store.load(kind) if not is_favorite_blacklisted(r)]


def _target_blacklisted(target) -> bool:
    return is_favorite_blacklisted({
        "kind": target.kind, "tg_id": target.tg_id,
        "username": target.username, "title": target.title, "link": target.link,
    })


async def _favorites_list() -> None:
    from bot.entitykind import is_bot_username
    by_name = lambda r: (r["username"] is None, (r["username"] or r["title"] or "").lower())
    groups = sorted(_visible_favorites("group"), key=_titled_key)
    channels = sorted(_visible_favorites("channel"), key=_titled_key)
    # 'user' + 'bot' favorites, split by the username rule (bots saved before this feature were 'user').
    people = _visible_favorites("user") + _visible_favorites("bot")
    users = sorted([r for r in people if not is_bot_username(r["username"])], key=by_name)
    bots = sorted([r for r in people if is_bot_username(r["username"])], key=by_name)
    if not groups and not channels and not users and not bots:
        print("⭐ No favorites yet. Save one with: favorites <user, group or channel>")
        return
    print("⭐ Favorites")
    if groups:
        print(f"📂 {_counted(len(groups), 'Group', 'Groups')}")
        _print_capped(groups, _fav_entity_line)
    if channels:
        print(f"📢 {_counted(len(channels), 'Channel', 'Channels')}")
        _print_capped(channels, _fav_entity_line)
    if users:
        print(f"👤 {_counted(len(users), 'User', 'Users')}")
        _print_capped(users, _fav_user_line)
    if bots:
        print(f"🤖 {_counted(len(bots), 'Bot', 'Bots')}")
        _print_capped(bots, _fav_user_line)


async def cmd_favorites(ctx, arg: str) -> None:
    if not arg:
        await _favorites_list()
        return

    parts = arg.split(maxsplit=1)
    if parts[0].lower() in REMOVE_WORDS and len(parts) > 1:
        parsed = parse_favorite_arg(parts[1].strip())
        if parsed is None:
            print("Usage: favorites remove <user, group or channel>")
            return
        mode, value = parsed
        username = value if mode == "username" else None
        tg_id = value if mode == "id" else None
        if favorites_store.remove(username, tg_id):
            print(f"🗑 Removed from favorites: {parts[1].strip()}")
        else:
            print(f"❌ '{parts[1].strip()}' isn't in your favorites.")
        return

    parsed = parse_favorite_arg(arg)
    if parsed is None:
        print("Usage: favorites <user, group or channel> — or favorites remove <…> to drop one.")
        return
    try:
        target = await resolve_target(ctx.bot_pool, ctx.get_client, parsed)
    except TelegramLookupUnavailable as e:
        print(f"⛔ Can't classify '{arg}' yet: not in the archive and Telegram lookup is unavailable ({e}).")
        return
    if target is None:
        print(f"❌ Couldn't find or classify '{arg}'.")
        return
    if _target_blacklisted(target):
        print(f"⛔ '{arg}' is blacklisted — not saved.")
        return
    line = _fav_target_line(target)
    if favorites_store.add(target) == "exists":
        print(f"ℹ️ Already in favorites:\n{line}")
    else:
        print(f"⭐ Saved to favorites:\n{line}")


# --- check (reachability of archived + favorite entities) ---------------------------------------

_CHECK_REASON = {
    "not_found": "no such user/group/channel — handle freed or deleted",
    "private": "private, or this account was removed from it",
    "invite_invalid": "private invite link expired or revoked",
    "restricted": "taken down by Telegram for violating its Terms of Service",
    "error": "temporary lookup failure",
}


def _check_name(target) -> str:
    if target is None:
        return "?"
    return f"{target.title}  ({target.link})" if target.link else target.title


def _check_line(x) -> str:
    star = "⭐ " if x.target.is_favorite else ""
    return f"   {status_glyph(x.status)} {star}{_check_name(x.target)}"


def _check_counts(label: str, items: list) -> None:
    ok = sum(1 for x in items if x.status == STATUS_OK)
    dead = sum(1 for x in items if is_dead(x.status))
    print(f"{label}: {ok} ✅ · {dead} ❌ · {len(items) - ok - dead} ⚠️ — {len(items)} total")


async def cmd_check(ctx, arg: str) -> None:
    tokens = arg.split()
    force = bool(tokens) and tokens[-1].lower() in ("force", "-f", "--force")
    if force:
        tokens = tokens[:-1]
    if not tokens:
        print("Usage: check <@username|link|id> [force] — or check all [force] / check prune / check links [force] / check links prune")
        return
    sub = tokens[0].lower()
    if sub == "all":
        await _check_all(ctx, force)
    elif sub == "prune":
        await _check_prune(ctx)
    elif sub == "links":
        if len(tokens) > 1 and tokens[1].lower() == "prune":
            await _check_links_prune(ctx)
        else:
            await _check_links(ctx, force)
    else:
        await _check_single(ctx, " ".join(tokens), force)


async def _check_single(ctx, raw: str, force: bool) -> None:
    client = await ctx.ensure_client()
    if client is None:
        print("⛔ Check unavailable: the Telethon session isn't logged in.")
        return
    try:
        target, status, previous, cached = await check_and_store(client, raw, force=force)
    except FloodWaitError as e:
        from collectors.throttle import floodwait_seconds, format_wait
        print(f"⏳ Telegram is rate-limiting this account (FloodWait) — try again in about {format_wait(floodwait_seconds(e))}.")
        return
    name = _check_name(target) if target else raw
    if status == STATUS_OK:
        print(f"✅ {name} — reachable.")
    elif is_dead(status):
        print(f"❌ {name} — unreachable ({_CHECK_REASON.get(status, _CHECK_REASON['error'])}).")
    else:
        print(f"⚠️ {name} — couldn't verify right now, try again later.")
    if cached:
        print(f"🕓 Cached result from {age_text(previous)} — add 'force' to re-check now.")
    elif previous is not None:
        print(f"ℹ️ Already checked {age_text(previous)} (was {status_glyph(previous.get('status'))}).")

    if status == STATUS_OK and target is not None:
        known = target.canonical_key in {t.canonical_key for t in await gather_targets(ctx.bot_pool)}
        if not known and input("Follow it (save to favorites)? [y/N]: ").strip().lower() == "y":
            await _check_follow(ctx, raw)


async def _check_follow(ctx, raw: str) -> None:
    parsed = parse_favorite_arg(raw)
    if parsed is None:
        print("Couldn't save — unrecognized target.")
        return
    try:
        target = await resolve_target(ctx.bot_pool, ctx.get_client, parsed)
    except TelegramLookupUnavailable as e:
        print(f"⛔ Can't save: {e}")
        return
    if target is None:
        print("Couldn't classify it to save.")
        return
    if favorites_store.add(target) == "exists":
        print(f"ℹ️ Already in favorites:\n{_fav_target_line(target)}")
    else:
        print(f"⭐ Saved to favorites:\n{_fav_target_line(target)}")


async def _check_all(ctx, force: bool) -> None:
    client = await ctx.ensure_client()
    if client is None:
        print("⛔ Check unavailable: the Telethon session isn't logged in.")
        return
    targets = sort_targets(await gather_targets(ctx.bot_pool))
    if not targets:
        print("Nothing to check yet — scrape a group or add a favorite first.")
        return
    print(f"🔎 Checking {_counted(len(targets), 'entity', 'entities')}… (this can take a while)")

    async def _progress(done: int, total: int) -> None:
        if done % 20 == 0 or done == total:
            print(f"   …{done}/{total}")

    run = await run_check_all(client, targets, force=force, on_progress=_progress)
    if run.aborted:
        from collectors.throttle import format_wait
        print(f"⚠️ Stopped early: Telegram asked us to wait about {format_wait(run.wait_seconds)} (FloodWait). Partial results saved.")
    if run.capped:
        print(f"⏸ Checked a batch this run — {run.remaining} still to go. Run it again (skip recent) to continue.")
    await _print_check_summary(ctx)


async def _print_check_summary(ctx) -> None:
    view = await build_view(ctx.bot_pool)
    groups = [x for x in view if x.target.kind == GROUP]
    channels = [x for x in view if x.target.kind == CHANNEL]
    users = [x for x in view if x.target.kind == USER]
    bots = [x for x in view if x.target.kind == BOT]
    checked = [x for x in view if x.entry is not None]

    print("\n🔎 Reachability")
    _check_counts("📂 Groups", groups)
    _check_counts("📢 Channels", channels)
    _check_counts("👤 Users", users)
    _check_counts("🤖 Bots", bots)
    print(f"🕓 Checked so far: {len(checked)}")

    for label, items in (("📂 Groups", groups), ("📢 Channels", channels), ("👤 Users", users), ("🤖 Bots", bots)):
        if items:
            print(f"\n{label}")
            _print_capped(items, _check_line)

    dead_total = sum(1 for x in view if is_dead(x.status))
    if dead_total:
        print(f"\n❌ {_counted(dead_total, 'inactive entity', 'inactive entities')} — remove with: check prune")


async def _check_prune(ctx) -> None:
    view = await build_view(ctx.bot_pool)
    dead = [x for x in view if is_dead(x.status)]
    if not dead:
        print("Nothing inactive to remove.")
        return
    print(f"⚠️ This removes {_counted(len(dead), 'inactive entity', 'inactive entities')} from CSVs and favorites (can't be undone):")
    _print_capped(dead, _check_line)
    if input("Type 'yes' to confirm: ").strip().lower() != "yes":
        print("Cancelled.")
        return
    n, _removed = await remove_inactive(ctx.bot_pool, {GROUP, CHANNEL, USER, BOT})
    await ctx.resync()
    print(f"🗑 Removed {_counted(n, 'inactive entity', 'inactive entities')}.")


async def _check_links(ctx, force: bool) -> None:
    client = await ctx.ensure_client()
    if client is None:
        print("⛔ Check unavailable: the Telethon session isn't logged in.")
        return
    targets = await gather_link_targets(ctx.bot_pool)
    if not targets:
        print("No links in the archive to check.")
        return
    print(f"🔗 Checking {_counted(len(targets), 'link', 'links')}… (this can take a while)")

    async def _progress(done: int, total: int) -> None:
        if done % 20 == 0 or done == total:
            print(f"   …{done}/{total}")

    run = await run_check_all(client, targets, force=force, on_progress=_progress)
    if run.aborted:
        from collectors.throttle import format_wait
        print(f"⚠️ Stopped early: Telegram asked us to wait about {format_wait(run.wait_seconds)} (FloodWait). Partial results saved.")
    if run.capped:
        print(f"⏸ Checked a batch this run — {run.remaining} still to go. Run it again (skip recent) to continue.")
    await _print_link_check_summary(ctx)


async def _print_link_check_summary(ctx) -> None:
    # Mirrors _print_check_summary, on the archived links: split by the kind each turned out to be.
    view = await build_link_view(ctx.bot_pool)
    groups = [x for x in view if x.target.kind == GROUP]
    channels = [x for x in view if x.target.kind == CHANNEL]
    users = [x for x in view if x.target.kind == USER]
    bots = [x for x in view if x.target.kind == BOT]
    checked = [x for x in view if x.entry is not None]

    print("\n🔗 Link reachability")
    _check_counts("📂 Groups", groups)
    _check_counts("📢 Channels", channels)
    _check_counts("👤 Users", users)
    _check_counts("🤖 Bots", bots)
    print(f"🕓 Checked so far: {len(checked)}")

    for label, items in (("📂 Groups", groups), ("📢 Channels", channels), ("👤 Users", users), ("🤖 Bots", bots)):
        if items:
            print(f"\n{label}")
            _print_capped(items, _check_line)

    dead_total = sum(1 for x in view if is_dead(x.status))
    if dead_total:
        print(f"\n❌ {_counted(dead_total, 'inactive link', 'inactive links')} — remove with: check links prune")


async def _check_links_prune(ctx) -> None:
    targets = await gather_link_targets(ctx.bot_pool)
    store = load_status()
    dead = [t for t in targets if is_dead((store.get(t.canonical_key) or {}).get("status"))]
    if not dead:
        print("Nothing inactive to remove.")
        return
    print(f"⚠️ This removes {_counted(len(dead), 'inactive link', 'inactive links')} from the link CSVs (can't be undone):")
    _print_capped(dead, lambda t: f"   • ❌ {t.title}")
    if input("Type 'yes' to confirm: ").strip().lower() != "yes":
        print("Cancelled.")
        return
    n, rows, _removed = await remove_inactive_links(ctx.bot_pool)
    await ctx.resync()
    print(f"🗑 Removed {_counted(n, 'inactive link', 'inactive links')} ({rows} CSV rows).")


# --- entity card (the CLI mirror of the bot's card: a numbered menu over the same cmd_*) ----------

def _card_handle(target) -> str:
    return card_mod.target_resolve_input(target) or (target.title or "")


def _print_card(target, state) -> None:
    icon = {CHANNEL: "📢", USER: "👤", BOT: "🤖"}.get(target.kind, "📂")
    name = f"{target.title}  ({target.link})" if target.link else (target.title or "?")
    print(f"\n{icon} {name}")
    print(f"{target.kind} · " + ("in your archive" if state.in_archive else "not archived yet"))
    if state.in_archive:
        if target.kind in (USER, BOT):
            print(f"📁 in {state.groups} groups · 🔗 {state.links} shared")
        else:
            print(f"👥 {state.members} · 🔗 {state.links}")
    if state.check_status:
        print(f"{status_glyph(state.check_status)} last check {age_text(state.check_entry)}")
    if state.is_favorite:
        print("⭐ in your favorites")


def _ask_limit() -> int:
    raw = input("How many recent messages to read? [500]: ").strip()
    return min(int(raw), 3000) if raw.isdigit() else 500


async def cmd_card(ctx, arg: str) -> None:
    raw = arg.strip()
    if not raw:
        print("Usage: card <@username|link|id> — or just paste one.")
        return
    try:
        target = await card_mod.resolve_identity(ctx.bot_pool, raw, ctx.get_client)
    except RateLimited as e:
        from collectors.throttle import format_wait
        print(f"⏳ Telegram is rate-limiting this account (FloodWait) — try again in about {format_wait(e.seconds)}.")
        return
    except TelegramLookupUnavailable as e:
        print(f"⛔ Check unavailable: {e}")
        return
    if target is None:
        print(f"❓ Couldn't find or resolve '{raw}'.")
        return
    handle = _card_handle(target)

    async def _add():
        if target.kind in (USER, BOT):
            if target.tg_id is None:
                print("Can't add this one — no resolvable id.")
                return
            write_registered_member(target.tg_id, target.username)
        else:
            write_registered(handle, target.title or handle, target.kind)
        await ctx.resync()
        print("📌 Added to archive.")

    async def _unregister():
        remove_registered_member(target.tg_id, target.username)
        await ctx.resync()
        print("🗑 Un-registered.")

    async def _scrape():
        if target.kind == GROUP:
            what = input("Scrape [1] members  [2] message senders  [3] links: ").strip()
        else:
            what = "3"  # a channel can only be link-scraped
        if what == "1":
            await cmd_scrapemembers(ctx, handle)
        elif what == "2":
            await cmd_scrapemessages(ctx, f"{handle} {_ask_limit()}")
        elif what == "3":
            await cmd_scrapelinks(ctx, f"{handle} {_ask_limit()}")

    async def _fav():
        await cmd_favorites(ctx, f"remove {handle}" if _is_fav(target) else handle)

    while True:
        state = await card_mod.archive_state(ctx.bot_pool, target)
        _print_card(target, state)
        actions: list[tuple[str, object]] = []
        if target.kind in (USER, BOT):
            if not state.in_archive:
                actions.append(("Add to archive", _add))
            else:
                actions.append(("Groups & links", lambda: cmd_searchusers(ctx, handle)))
                if state.groups == 0:  # a standalone registered member -> can un-register
                    actions.append(("Un-register", _unregister))
        else:
            if not state.in_archive:
                actions.append(("Add to archive", _add))
            if target.kind == GROUP and state.members:
                actions.append(("Members", lambda: cmd_members(ctx, handle)))
            if state.links:
                actions.append(("Links", lambda: cmd_links(ctx, handle)))
            actions.append(("Re-scrape" if (state.members or state.links) else "Scrape", _scrape))
            if state.in_archive:
                actions.append(("Export", lambda: cmd_export(ctx, handle)))
                actions.append(("Delete", lambda: cmd_delete(ctx, handle)))
        actions.append(("Unfavorite" if state.is_favorite else "Favorite", _fav))
        actions.append(("Check", lambda: cmd_check(ctx, f"{handle} force")))

        for i, (label, _fn) in enumerate(actions, 1):
            print(f"  [{i}] {label}")
        choice = input("Pick a number (Enter to close): ").strip()
        if not choice.isdigit():
            return
        idx = int(choice) - 1
        if not 0 <= idx < len(actions):
            print("Invalid choice.")
            continue
        await actions[idx][1]()


def _is_fav(target) -> bool:
    return any(card_mod._fav_match(i, target) for i in favorites_store.load(target.kind))


# --- scraping (writes CSV, then re-syncs the DB so search sees it right away) --------------------

def _split_group_and_limit(arg: str, default_limit: int, max_limit: int) -> tuple[str, int]:
    parts = arg.split()
    if parts and parts[-1].isdigit():
        return " ".join(parts[:-1]), min(int(parts[-1]), max_limit)
    return " ".join(parts), default_limit


def _scrape_fail_text(err) -> str:
    """Plain-text mirror of the bot's scrape failure messages (bot/modules/start.py), keyed off the
    same typed reason so the CLI explains WHY a scrape failed."""
    from collectors.scrape_errors import NOT_FOUND, NOT_MEMBER, RATE_LIMITED, WRONG_TYPE
    if err.reason == NOT_FOUND:
        return "❌ Not found — check the @username or link (a private group needs a valid invite link)."
    if err.reason == NOT_MEMBER:
        return "🔒 Private and the scraping account isn't a member yet — join it in Telegram with that account, then scrape."
    if err.reason == WRONG_TYPE:
        return (f"❌ That's a {err.detail or 'channel'}, not a group — members and message senders come "
                "only from groups/supergroups. For a channel, use: scrapelinks.")
    if err.reason == RATE_LIMITED:
        from collectors.throttle import format_wait
        secs = int(err.detail) if (err.detail or "").isdigit() else None
        return f"⏳ Telegram is rate-limiting this account (FloodWait) — try again in about {format_wait(secs)}. Anything collected is saved."
    return "❌ Found it, but there was nothing to collect (empty, or nothing new)."


async def _run_scrape(ctx, coro_factory, after) -> None:
    from collectors.scrape_errors import ScrapeError
    client = await ctx.ensure_client()
    if client is None:
        print("⛔ Scraping unavailable: the Telethon session isn't logged in.")
        return
    try:
        result = await coro_factory(client)
    except ScrapeError as e:
        print(_scrape_fail_text(e))
        return
    except Exception as e:
        print(f"❌ Scraping error: {e}")
        return
    if not result:  # safety net: the scrapers now raise ScrapeError instead of returning None
        return
    await ctx.resync()
    after(result)


async def cmd_scrapemembers(ctx, arg: str) -> None:
    if not arg:
        print("Usage: scrapemembers <group>")
        return
    await _run_scrape(
        ctx, lambda client: extract_members(client, arg),
        lambda r: print(f"✅ Saved {_counted(r['total'], 'member', 'members')} from '{r['group_title']}' — browse with: groups"),
    )


async def cmd_scrapemessages(ctx, arg: str) -> None:
    group_input, limit = _split_group_and_limit(arg, MSG_DEFAULT_LIMIT, MSG_MAX_LIMIT)
    if not group_input:
        print("Usage: scrapemessages <group> <limit>")
        return
    await _run_scrape(
        ctx, lambda client: scrape_from_messages(client, group_input, limit),
        lambda r: print(f"✅ Saved {_counted(r['total'], 'user', 'users')} from '{r['group_title']}' — browse with: groups"),
    )


async def cmd_scrapelinks(ctx, arg: str) -> None:
    group_input, limit = _split_group_and_limit(arg, LINKS_DEFAULT_LIMIT, LINKS_MAX_LIMIT)
    if not group_input:
        print("Usage: scrapelinks <group or channel> <limit>")
        return
    await _run_scrape(
        ctx, lambda client: extract_links(client, group_input, limit),
        lambda r: print(f"✅ {r['links_saved']} links saved from '{r['group_title']}' — browse with: groups / channels"),
    )
