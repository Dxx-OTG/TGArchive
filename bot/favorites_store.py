"""Favorites persistence: a single CSV in output/, like the rest of the data.

Not imported into the database (favorites need no relational queries), so there's no table and no
migration - the bot reads and writes this CSV directly. Removal is a real delete from the file.
"""
import csv
from pathlib import Path

from bot.favorites import ResolvedTarget

FAVORITES_DIR = Path("output") / "Favorites"
FAVORITES_CSV = FAVORITES_DIR / "favorites.csv"
FIELDNAMES = ["Kind", "Tg_id", "Username", "Title", "Link"]


def _to_item(row: dict) -> dict:
    tg = (row.get("Tg_id") or "").strip()
    return {
        "kind": (row.get("Kind") or "").strip(),
        "tg_id": int(tg) if tg.lstrip("-").isdigit() else None,
        "username": (row.get("Username") or "").strip() or None,
        "title": (row.get("Title") or "").strip() or None,
        "link": (row.get("Link") or "").strip() or None,
    }


def load(kind: str | None = None) -> list[dict]:
    """Saved favorites, optionally filtered by kind ('user'/'group'), in file order."""
    if not FAVORITES_CSV.exists():
        return []
    out = []
    with open(FAVORITES_CSV, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            item = _to_item(row)
            if item["kind"] and (kind is None or item["kind"] == kind):
                out.append(item)
    return out


def _write(rows: list[dict]) -> None:
    FAVORITES_DIR.mkdir(parents=True, exist_ok=True)
    tmp = FAVORITES_CSV.with_suffix(".csv.new")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for r in rows:
            writer.writerow({
                "Kind": r["kind"],
                "Tg_id": "" if r["tg_id"] is None else r["tg_id"],
                "Username": r["username"] or "",
                "Title": r["title"] or "",
                "Link": r["link"] or "",
            })
    tmp.replace(FAVORITES_CSV)


def _matches(row: dict, username: str | None, tg_id: int | None, link: str | None = None) -> bool:
    if username and row["username"] and row["username"].lower() == username.lower():
        return True
    if tg_id is not None and row["tg_id"] is not None and row["tg_id"] == tg_id:
        return True
    # A private group has no username/id - match it by its invite link so it (un)favorites like the rest.
    return bool(link) and row["link"] is not None and row["link"] == link


def find(*, username: str | None = None, tg_id: int | None = None, link: str | None = None) -> ResolvedTarget | None:
    """The saved favorite matching this handle / id / invite link, as a ResolvedTarget, or None - so a
    favorited entity's card opens from this CSV with NO Telegram call, even when it isn't archived."""
    for row in load():
        if _matches(row, username, tg_id, link):
            return ResolvedTarget(kind=row["kind"], tg_id=row["tg_id"], username=row["username"],
                                  title=row["title"], link=row["link"])
    return None


def add(target: ResolvedTarget) -> str:
    """Append a favorite. 'exists' if the same identity is already saved, else 'added'."""
    rows = load()
    for row in rows:
        if row["kind"] == target.kind and _matches(row, target.username, target.tg_id, target.link):
            return "exists"
    rows.append({
        "kind": target.kind, "tg_id": target.tg_id, "username": target.username,
        "title": target.title, "link": target.link,
    })
    _write(rows)
    return "added"


def remove(username: str | None, tg_id: int | None, link: str | None = None) -> int:
    """Delete every favorite matching this handle, id, or invite link. Returns how many were removed."""
    rows = load()
    kept = [r for r in rows if not _matches(r, username, tg_id, link)]
    removed = len(rows) - len(kept)
    if removed:
        _write(kept)
    return removed
