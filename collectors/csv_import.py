import csv
import json
from datetime import datetime
from pathlib import Path

import asyncpg

from bot.group_links import canonical_group_key, normalize_entity_link
from collectors.repository import save_legacy_csv_import, save_links_import
from db.queries.links import link_key

# (folder, source): source must match the membership_source enum in the DB.
FOLDERS = [
    (Path("output") / "Members From Groups", "participants"),
    (Path("output") / "Members From Messages", "messages"),
]

# Extracted-links CSVs. These ARE imported (into extracted_links): CLI/ExtractLinks.py now writes
# an Invite_link column, so a link CSV ties to the same group as the member CSVs. Older CSVs without
# that column fall back to the filename title.
LINK_FOLDER = Path("output") / "Extracted Links"
LINK_SUFFIX = "_links"
LINK_CSV_HEADER = ["Invite_link", "Link", "User_id", "Username", "Date", "Kind"]

# "Registered" CSVs: a group/channel added to the archive WITHOUT scraping yet. Header + one identity
# row (Invite_link/Title/Kind), no members. They create the group and, crucially, keep it from being
# pruned by reconcile_with_csv even though it has 0 members and 0 links. A later scrape
# of the same title merges into it.
REGISTERED_FOLDER = Path("output") / "Registered"

# The same idea for a standalone user/bot added from its card (a leaf entity that isn't a member of any
# scraped group): a one-row CSV (User_id/Username) creates the member with no group_members link, and
# reconcile keeps it (see registered_member_ids). This is how a user/bot lands in Browse with 0 groups.
REGISTERED_MEMBERS_FOLDER = Path("output") / "Registered Members"

# Remembers mtimes of already-imported files so the watcher doesn't re-read unchanged CSVs.
MANIFEST_FILE = Path("output") / ".import_manifest.json"

NO_USERNAME = "(No Username)"


def _load_manifest() -> dict[str, float]:
    if not MANIFEST_FILE.exists():
        return {}
    try:
        return json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_manifest(manifest: dict[str, float]) -> None:
    MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_FILE.write_text(json.dumps(manifest), encoding="utf-8")


def read_csv(file: Path) -> tuple[str, dict[str, str]]:
    """Return (invite_input, {user_id: username}). Falls back to the file name if the
    Invite_link column is missing, so hand-pasted CSVs still work."""
    users: dict[str, str] = {}
    invite_input = file.stem.replace("_", " ")

    with open(file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            uid = (row.get("User_id") or "").strip()
            if not uid.isdigit():
                continue

            link = (row.get("Invite_link") or "").strip()
            if link:
                invite_input = link

            uname = (row.get("Username") or "").strip()
            users[uid] = uname or NO_USERNAME

    return invite_input, users


async def import_file(pool: asyncpg.Pool, file: Path, source: str) -> int:
    invite_input, users = read_csv(file)
    if not users:
        return 0

    title = file.stem.replace("_", " ")
    return await save_legacy_csv_import(pool, invite_input=invite_input, title=title, members=users, source=source)


def link_csv_title(file: Path) -> str:
    """Group title behind a links CSV, from its 'NAME_links.csv' filename - matched to the member
    import's title (file.stem.replace('_',' ')) so both resolve to the same group."""
    stem = file.stem
    base = stem[: -len(LINK_SUFFIX)] if stem.endswith(LINK_SUFFIX) else stem
    return base.replace("_", " ")


def remove_links_from_csvs(dead_keys: set[str]) -> int:
    """Drop rows whose link_key is in `dead_keys` from every links CSV (Check Links removal); the
    watcher then prunes those rows from the DB. Returns how many rows were removed. link_key ignores
    the message id, so a CSV's dirty 't.me/x/123' still matches the dead key 't.me/x'."""
    from db.queries.links import link_key

    if not dead_keys or not LINK_FOLDER.exists():
        return 0
    removed = 0
    for file in LINK_FOLDER.glob("*.csv"):
        try:
            with open(file, "r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                rows = list(reader)
        except OSError:
            continue
        kept = [r for r in rows if link_key((r.get("Link") or "").strip()) not in dead_keys]
        if len(kept) == len(rows):
            continue
        removed += len(rows) - len(kept)
        with open(file, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames or LINK_CSV_HEADER, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(kept)
    return removed


def _link_csv_invite(file: Path) -> str:
    """The Invite_link of a links CSV (first row that carries one) so it can be matched by canonical
    identity for deletion; falls back to the filename title for old CSVs without the column."""
    try:
        with open(file, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                inv = (row.get("Invite_link") or "").strip()
                if inv:
                    return inv
    except OSError:
        pass
    return link_csv_title(file)


def read_link_csv(file: Path) -> tuple[str, str, list[dict]]:
    """Return (invite_input, kind, rows) for an extracted-links CSV (Invite_link/Link/User_id/
    Username/Date/Kind). invite_input comes from the Invite_link column if present (so the links tie
    to the same group as the members), else the filename title. kind ('group'/'channel') is the
    scraped source type; old CSVs without a Kind column default to 'group'."""
    invite_input = link_csv_title(file)
    kind = "group"
    out = []
    with open(file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            raw = (row.get("Link") or "").strip()
            # Keep only entity links, reduced to the entity (message ids/queries stripped, service
            # links dropped) - so old CSVs full of message/discussion links get cleaned on import too.
            link = normalize_entity_link(raw)
            if not link:
                continue

            inv = (row.get("Invite_link") or "").strip()
            if inv:
                invite_input = inv

            row_kind = (row.get("Kind") or "").strip().lower()
            if row_kind in ("group", "channel"):
                kind = row_kind

            uid = (row.get("User_id") or "").strip()
            uname = (row.get("Username") or "").strip()
            date_str = (row.get("Date") or "").strip()

            try:
                message_date = datetime.strptime(date_str, "%Y-%m-%d %H:%M") if date_str else None
            except ValueError:
                message_date = None

            out.append({
                "link": link,
                "sender_user_id": int(uid) if uid.isdigit() else None,
                "sender_username": uname if uname and uname not in ("(None)", "(Unknown)") else None,
                "message_date": message_date,
            })

    # Drop the group's own link (self-reference) - a channel's own link scraped from its own posts.
    own = normalize_entity_link(invite_input)
    if own:
        out = [r for r in out if r["link"].lower() != own.lower()]
    return invite_input, kind, out


def find_group_csv_files(canonical_key: str, title: str, which: str = "all") -> list[Path]:
    """CSV files belonging to a group/channel, for deletion. which='members' -> the member CSVs
    (matched by canonical identity, like the member import); 'links' -> the links CSV (matched by
    title, like the link import); 'all' -> both. Deleting these lets the watcher prune the DB rows."""
    files: list[Path] = []
    target_title = (title or "").strip().lower()

    if which in ("members", "all"):
        for folder, _source in FOLDERS:
            if not folder.exists():
                continue
            for file in folder.glob("*.csv"):
                invite_input, _users = read_csv(file)
                if canonical_group_key(file.stem.replace("_", " "), None, invite_input) == canonical_key:
                    files.append(file)

    if which in ("links", "all") and LINK_FOLDER.exists():
        for file in LINK_FOLDER.glob("*.csv"):
            csv_title = link_csv_title(file)
            # Match by canonical identity first (like the members import): the link CSV's Invite_link
            # column ties it to the same @username/link even when the live title differs from the
            # filename (e.g. a channel whose Telegram title has emoji the filename stripped). Title
            # equality stays as a fallback for old CSVs with no Invite_link column.
            if (canonical_group_key(csv_title, None, _link_csv_invite(file)) == canonical_key
                    or csv_title.strip().lower() == target_title):
                files.append(file)

    # Registered CSVs: same canonical-first match (they carry an Invite_link too), title as fallback.
    if which in ("registered", "all") and REGISTERED_FOLDER.exists():
        for file in REGISTERED_FOLDER.glob("*.csv"):
            invite, title, _kind = read_registered_csv(file)
            if (canonical_group_key(title, None, invite) == canonical_key
                    or title.strip().lower() == target_title):
                files.append(file)

    return files


async def import_links(pool: asyncpg.Pool, *, only_new: bool = False) -> list[str]:
    """Import the extracted-links CSVs into extracted_links (the only writer of that table). Shares
    the same mtime manifest as import_all; only_new skips files with unchanged mtime."""
    manifest = _load_manifest()
    manifest = {path: mtime for path, mtime in manifest.items() if Path(path).exists()}
    log_lines: list[str] = []

    if LINK_FOLDER.exists():
        for file in sorted(LINK_FOLDER.glob("*.csv")):
            key = str(file)
            mtime = file.stat().st_mtime

            if only_new and manifest.get(key) == mtime:
                continue

            invite_input, kind, rows = read_link_csv(file)
            manifest[key] = mtime
            if not rows:
                continue

            saved = await save_links_import(pool, invite_input=invite_input, title=link_csv_title(file), kind=kind, links=rows)
            log_lines.append(f"{LINK_FOLDER.name}/{file.name}: {saved} links imported")

    _save_manifest(manifest)
    return log_lines


def read_registered_csv(file: Path) -> tuple[str, str, str]:
    """(invite_input, title, kind) for a registered CSV. invite_input/title fall back to the filename;
    kind ('group'/'channel') defaults to 'group'."""
    title = file.stem.replace("_", " ")
    invite_input = title
    kind = "group"
    with open(file, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            inv = (row.get("Invite_link") or "").strip()
            if inv:
                invite_input = inv
            ttl = (row.get("Title") or "").strip()
            if ttl:
                title = ttl
            row_kind = (row.get("Kind") or "").strip().lower()
            if row_kind in ("group", "channel"):
                kind = row_kind
            break  # a registered CSV carries a single identity row
    return invite_input, title, kind


def write_registered(invite_input: str, title: str, kind: str) -> Path:
    """Create the registered CSV for a group/channel (add-to-archive without scraping). Returns the
    path. The watcher/CLI sync then creates the group in the DB."""
    from collectors.naming import safe_group_filename
    REGISTERED_FOLDER.mkdir(parents=True, exist_ok=True)
    path = REGISTERED_FOLDER / f"{safe_group_filename(title, 0)}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["Invite_link", "Title", "Kind"])
        writer.writeheader()
        writer.writerow({"Invite_link": invite_input, "Title": title, "Kind": kind})
    return path


async def import_registered(pool: asyncpg.Pool, *, only_new: bool = False) -> list[str]:
    """Create the group/channel behind each registered CSV, without members. Shares the mtime manifest
    with the other imports; only_new skips unchanged files."""
    from db.queries import groups as groups_q

    manifest = _load_manifest()
    manifest = {path: mtime for path, mtime in manifest.items() if Path(path).exists()}
    log_lines: list[str] = []

    if REGISTERED_FOLDER.exists():
        for file in sorted(REGISTERED_FOLDER.glob("*.csv")):
            key = str(file)
            mtime = file.stat().st_mtime
            if only_new and manifest.get(key) == mtime:
                continue
            invite_input, title, kind = read_registered_csv(file)
            manifest[key] = mtime
            await groups_q.find_or_create_group_by_title(pool, title=title, invite_input=invite_input, kind=kind)
            log_lines.append(f"{REGISTERED_FOLDER.name}/{file.name}: registered '{title}'")

    _save_manifest(manifest)
    return log_lines


def registered_titles() -> set[str]:
    """Lowercased titles backed by a registered CSV, so reconcile keeps their (memberless) groups."""
    titles: set[str] = set()
    if REGISTERED_FOLDER.exists():
        for file in REGISTERED_FOLDER.glob("*.csv"):
            _invite, title, _kind = read_registered_csv(file)
            titles.add(title.strip().lower())
    return titles


# --- registered members (standalone user/bot added from a card, no group) ------------------------

def write_registered_member(tg_user_id: int, username: str | None) -> Path:
    """Add a standalone user/bot to the archive WITHOUT scraping (from its card): a one-row CSV
    (User_id/Username). The sync then creates the memberless member; reconcile keeps it."""
    from collectors.naming import safe_group_filename
    REGISTERED_MEMBERS_FOLDER.mkdir(parents=True, exist_ok=True)
    path = REGISTERED_MEMBERS_FOLDER / f"{safe_group_filename(username or str(tg_user_id), 0)}.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["User_id", "Username"])
        writer.writeheader()
        writer.writerow({"User_id": tg_user_id, "Username": username or ""})
    return path


def read_registered_member_csv(file: Path) -> tuple[int, str | None] | None:
    """(tg_user_id, username) from a registered-member CSV, or None if it has no valid id row."""
    try:
        with open(file, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                uid = (row.get("User_id") or "").strip()
                if uid.lstrip("-").isdigit():
                    return int(uid), (row.get("Username") or "").strip() or None
    except OSError:
        pass
    return None


def registered_member_ids() -> set[int]:
    """tg_user_ids backed by a registered-member CSV, so reconcile keeps their (group-less) members."""
    ids: set[int] = set()
    if REGISTERED_MEMBERS_FOLDER.exists():
        for file in REGISTERED_MEMBERS_FOLDER.glob("*.csv"):
            rec = read_registered_member_csv(file)
            if rec is not None:
                ids.add(rec[0])
    return ids


def remove_registered_member(tg_user_id: int | None, username: str | None) -> int:
    """Delete the registered-member CSV(s) matching this id/username (un-register a standalone user/bot
    from its card). Returns how many were removed; the watcher then prunes the now-orphan member."""
    if not REGISTERED_MEMBERS_FOLDER.exists():
        return 0
    removed = 0
    for file in REGISTERED_MEMBERS_FOLDER.glob("*.csv"):
        rec = read_registered_member_csv(file)
        if rec is None:
            continue
        rid, runame = rec
        if (tg_user_id is not None and rid == tg_user_id) or (username and runame and runame.lower() == username.lower()):
            try:
                file.unlink()
                removed += 1
            except OSError:
                pass
    return removed


async def import_registered_members(pool: asyncpg.Pool, *, only_new: bool = False) -> list[str]:
    """Create the (group-less) member behind each registered-member CSV. Shares the mtime manifest with
    the other imports; only_new skips unchanged files. reconcile keeps these members from being pruned."""
    from db.queries import members as members_q

    manifest = _load_manifest()
    manifest = {path: mtime for path, mtime in manifest.items() if Path(path).exists()}
    log_lines: list[str] = []

    if REGISTERED_MEMBERS_FOLDER.exists():
        for file in sorted(REGISTERED_MEMBERS_FOLDER.glob("*.csv")):
            key = str(file)
            mtime = file.stat().st_mtime
            if only_new and manifest.get(key) == mtime:
                continue
            rec = read_registered_member_csv(file)
            manifest[key] = mtime
            if rec is None:
                continue
            tg_id, uname = rec
            await members_q.upsert_member(pool, tg_user_id=tg_id, username=uname)
            log_lines.append(f"{REGISTERED_MEMBERS_FOLDER.name}/{file.name}: registered member {uname or tg_id}")

    _save_manifest(manifest)
    return log_lines


async def import_all(pool: asyncpg.Pool, *, only_new: bool = False) -> list[str]:
    """Import the members CSVs into members/groups/group_members (the only writer of those tables).
    only_new=False re-reads everything; only_new=True (watcher) skips files with unchanged mtime.
    Files no longer on disk are dropped from the manifest."""
    manifest = _load_manifest()
    manifest = {path: mtime for path, mtime in manifest.items() if Path(path).exists()}
    log_lines: list[str] = []

    for folder, source in FOLDERS:
        if not folder.exists():
            continue

        for file in sorted(folder.glob("*.csv")):
            key = str(file)
            mtime = file.stat().st_mtime

            if only_new and manifest.get(key) == mtime:
                continue

            saved = await import_file(pool, file, source)
            manifest[key] = mtime
            log_lines.append(f"{folder.name}/{file.name}: {saved} rows imported")

    _save_manifest(manifest)
    return log_lines


async def reconcile_with_csv(pool: asyncpg.Pool, *, dry_run: bool = False) -> dict[str, int]:
    """Prune DB rows of members/groups no longer backed by any CSV, so the DB mirrors the CSVs.
    Run after import_all; always scans all CSVs. dry_run=True only counts, deletes nothing."""
    desired_members: set[tuple[str, int, str]] = set()
    for folder, source in FOLDERS:
        if not folder.exists():
            continue
        for file in folder.glob("*.csv"):
            invite_input, users = read_csv(file)
            title = file.stem.replace("_", " ")
            key = canonical_group_key(title, None, invite_input)
            for uid in users:
                desired_members.add((key, int(uid), source))

    existing_gm = await pool.fetch(
        """
        SELECT gm.id, g.title, g.username, g.invite_input, m.tg_user_id, gm.source
        FROM group_members gm
        JOIN groups g ON g.id = gm.group_id
        JOIN members m ON m.id = gm.member_id
        """
    )
    gm_to_remove = [
        r["id"] for r in existing_gm
        if (canonical_group_key(r["title"], r["username"], r["invite_input"]), r["tg_user_id"], r["source"])
        not in desired_members
    ]

    # Same idea for extracted links, but keyed by group TITLE (links attach to a group by title, see
    # find_or_create_group_by_title), so the keys here match the group the links actually live on.
    desired_links: set[tuple[str, str]] = set()
    if LINK_FOLDER.exists():
        for file in LINK_FOLDER.glob("*.csv"):
            _invite_input, _kind, rows = read_link_csv(file)
            key = link_csv_title(file).strip().lower()
            for row in rows:
                desired_links.add((key, link_key(row["link"])))

    existing_links = await pool.fetch(
        """
        SELECT el.id, g.title, el.link_key
        FROM extracted_links el
        JOIN groups g ON g.id = el.group_id
        """
    )
    links_to_remove = [
        r["id"] for r in existing_links
        if ((r["title"] or "").strip().lower(), r["link_key"]) not in desired_links
    ]

    result = {
        "group_members_removed": len(gm_to_remove),
        "extracted_links_removed": len(links_to_remove),
        "orphan_members_removed": 0,
        "orphan_groups_removed": 0,
    }

    if dry_run:
        return result

    if gm_to_remove:
        await pool.execute("DELETE FROM group_members WHERE id = ANY($1::bigint[])", gm_to_remove)
    if links_to_remove:
        await pool.execute("DELETE FROM extracted_links WHERE id = ANY($1::bigint[])", links_to_remove)

    # Prune members with no group membership - EXCEPT ones backed by a registered-member CSV (a
    # standalone user/bot added from its card): those are meant to persist group-less until scraped.
    kept_member_ids = list(registered_member_ids())
    result["orphan_members_removed"] = await pool.fetchval(
        """
        WITH deleted AS (
            DELETE FROM members
            WHERE id NOT IN (SELECT DISTINCT member_id FROM group_members)
              AND tg_user_id != ALL($1::bigint[])
            RETURNING id
        )
        SELECT count(*) FROM deleted
        """,
        kept_member_ids,
    )
    # Prune groups with no members and no links - EXCEPT ones backed by a registered CSV (added to the
    # archive without scraping): those are meant to persist empty until scraped.
    kept_titles = registered_titles()
    orphans = await pool.fetch(
        """
        SELECT id, title FROM groups
        WHERE id NOT IN (SELECT DISTINCT group_id FROM group_members)
          AND id NOT IN (SELECT DISTINCT group_id FROM extracted_links)
        """
    )
    orphan_ids = [r["id"] for r in orphans if (r["title"] or "").strip().lower() not in kept_titles]
    if orphan_ids:
        await pool.execute("DELETE FROM groups WHERE id = ANY($1::bigint[])", orphan_ids)
    result["orphan_groups_removed"] = len(orphan_ids)

    return result
