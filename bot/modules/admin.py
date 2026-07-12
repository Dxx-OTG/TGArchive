"""Data helpers behind the hub's Data menu and the entity card: stats totals, per-entity export, the
full-archive export zip, and the "delete all" wipe. The hub (bot/modules/start.py) and the card call
these directly; the only handler here is the "delete all" confirmation the hub arms.
"""
import csv
import io
import zipfile
from html import escape
from pathlib import Path

from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardMarkup, Message

from bot.i18n import plural, t
from bot.log import log
from bot.pagination import btn, safe_answer, safe_edit_text
from db.blacklist import resolve_blacklist
from db.pool import get_pool
from db.queries import links as links_q
from db.queries import members as members_q

router = Router(name="admin")

OUTPUT_DIR = Path("output")
FAVORITES_DIR = OUTPUT_DIR / "Favorites"


def _back_to_data() -> InlineKeyboardMarkup:
    """Single Back button to the Data menu, for the terminal Export/Delete results shown in place."""
    return InlineKeyboardMarkup(inline_keyboard=[[btn(t("hub_btn_back"), "home:data")]])


def _csv_document(filename: str, header: list[str], rows: list[list]) -> BufferedInputFile:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return BufferedInputFile(buffer.getvalue().encode("utf-8"), filename=filename)


def _output_csvs(*, include_favorites: bool) -> list[Path]:
    """Every CSV under output/, optionally minus the favorites file (favorites are never deleted)."""
    if not OUTPUT_DIR.exists():
        return []
    files = sorted(OUTPUT_DIR.rglob("*.csv"))
    if not include_favorites:
        fav = FAVORITES_DIR.resolve()
        files = [f for f in files if fav not in f.resolve().parents]
    return files


def _unlink_all(files: list[Path]) -> list[Path]:
    deleted: list[Path] = []
    for file in files:
        try:
            file.unlink()
            deleted.append(file)
        except OSError as e:
            log(f"⚠️ delete: couldn't remove {file}: {e}")
    return deleted


async def stats_counts(pool) -> dict:
    """The stats totals (blacklist excluded), for the hub's in-place stats view."""
    bl = await resolve_blacklist(pool)
    row = await pool.fetchrow(
        "SELECT (SELECT count(*) FROM groups WHERE kind = 'group' AND id != ALL($1::bigint[])) AS groups,"
        " (SELECT count(*) FROM groups WHERE kind = 'channel' AND id != ALL($1::bigint[])) AS channels,"
        " (SELECT count(*) FROM extracted_links WHERE id != ALL($2::bigint[])) AS links",
        bl.group_ids, bl.link_ids,
    )
    by_kind = await members_q.count_members_by_kind(pool)  # members split into users vs bots
    return {
        "groups": row["groups"], "channels": row["channels"], "links": row["links"],
        "users": by_kind["users"], "bots": by_kind["bots"],
        "with_username": by_kind["with_username"], "without_username": by_kind["without_username"],
    }


async def send_group_export(message: Message, group_id: int, title: str) -> bool:
    """Send this group's members and/or links as CSV documents (a channel has only links). Returns
    False if there's nothing to send. Used by the entity card's Export."""
    pool = get_pool()
    members = await members_q.list_group_members(pool, group_id)
    links = await links_q.links_for_group(pool, group_id)
    if not members and not links:
        return False

    if members:
        doc = _csv_document(
            f"{title}.csv",
            ["User_id", "Username", "Source"],
            [[r["tg_user_id"], r["username"] or "", r["source"]] for r in members],
        )
        await message.answer_document(
            doc, caption=t("export_caption", title=escape(title), n=len(members), word=plural(len(members), "Member", "Members"))
        )
    if links:
        doc = _csv_document(
            f"{title}_links.csv",
            ["Link", "Username", "Date"],
            [
                [r["link"], r["sender_username"] or "", f"{r['message_date']:%Y-%m-%d %H:%M}" if r["message_date"] else ""]
                for r in links
            ],
        )
        await message.answer_document(
            doc, caption=t("export_links_caption", title=escape(title), n=len(links), word=plural(len(links), "Link", "Links"))
        )
    return True


async def _export_full_zip(message: Message) -> None:
    """Hub Data -> Export All: every output CSV (favorites included) bundled into one zip."""
    files = _output_csvs(include_favorites=True)
    if not files:
        await safe_edit_text(message, t("export_all_empty"), _back_to_data())
        return
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for file in files:
            archive.write(file, file.relative_to(OUTPUT_DIR))
    doc = BufferedInputFile(buffer.getvalue(), filename="tgarchive_output.zip")
    await message.answer_document(doc, caption=t("export_all_caption", n=len(files), word=plural(len(files), "File", "Files")))


@router.callback_query(F.data == "delall:yes")
async def on_delete_all_confirm(callback: CallbackQuery) -> None:
    """Hub Data -> Delete All, confirmed. Deletes every scraped CSV (favorites kept); the watcher then
    prunes the DB. No direct DB write."""
    await safe_answer(callback)
    n = len(_unlink_all(_output_csvs(include_favorites=False)))
    await safe_edit_text(callback.message, t("delete_all_done", n=n, word=plural(n, "File", "Files")), _back_to_data())
