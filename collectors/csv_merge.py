"""Read what's already in a scrape CSV, so a re-scrape can MERGE (keep old rows, add only new ones)
instead of overwriting. Deliberately dependency-free (just csv/pathlib) so the scrapers stay light. A re-scrape must never drop previously collected members/links."""
import csv
from pathlib import Path


def existing_member_users(output_file: Path, no_username: str) -> dict[str, str]:
    """{user_id: username} already saved in a member CSV (empty when the file is new)."""
    users: dict[str, str] = {}
    if output_file.exists():
        with open(output_file, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                uid = (row.get("User_id") or "").strip()
                if uid.isdigit():
                    users[uid] = (row.get("Username") or "").strip() or no_username
    return users


def existing_link_rows(output_file: Path, link_key) -> tuple[list[dict], set[str]]:
    """(raw rows, their dedup keys) already saved in a links CSV, so the scrape can skip them and
    write them back unchanged."""
    rows: list[dict] = []
    keys: set[str] = set()
    if output_file.exists():
        with open(output_file, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rows.append(row)
                link = (row.get("Link") or "").strip()
                if link:
                    keys.add(link_key(link))
    return rows, keys
