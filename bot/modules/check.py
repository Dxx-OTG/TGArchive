"""Reachability check driven from the /start hub (Data -> Check -> Check All) and the entity card.

Check All probes every scraped group/channel plus favorite users/groups/channels (the members table
is out of scope - too big, ban risk), skipping ones checked in the last 24h unless forced. The
summary opens paginated lists per kind, each with a confirm-guarded "remove inactive". A single
entity is checked from its card (bot/modules/card.py).

Shares the single-Telethon-job lock with the scrapers (bot/job_lock.py) so the two never drive the
client at once. Never writes the DB directly: removal deletes CSVs and lets the watcher prune. """
import asyncio
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot import check_view
from bot.entitykind import BOT, CHANNEL, GROUP, USER
from bot.i18n import plural, t
from bot.job_lock import acquire_job, cooldown_wait, release_job
from bot.pagination import btn, safe_answer, safe_edit_text
from bot.telethon_client import get_scrape_client
from collectors.throttle import format_wait
from collectors.check import (
    gather_link_targets,
    gather_targets,
    remove_inactive,
    remove_inactive_links,
    run_check_all,
    sort_targets,
)
from db.pool import get_pool

router = Router(name="check")

_REMOVE_KIND = {"g": GROUP, "c": CHANNEL, "u": USER, "b": BOT}
_PROGRESS_EVERY = 10

# Holds the running check's stop Event while a Check All / Check Links is probing, so the Stop
# button's handler can end it. Only one check runs at a time (job_lock), so a single slot is enough.
_active_stop: "asyncio.Event | None" = None


def _stop_kb() -> InlineKeyboardMarkup:
    """The Stop button shown on the live progress message. It ends the run and reveals the partial
    summary (which has its own Back), so it doubles as the way out of a running check."""
    return InlineKeyboardMarkup(inline_keyboard=[[btn(t("hub_btn_stop"), "chkstop")]])


def _back_to_check(*, links: bool = False) -> InlineKeyboardMarkup:
    """Single Back button for the terminal states (busy / unavailable / nothing to check) that would
    otherwise strand the user with no way back. Goes to the pre-check OPTIONS screen this run was
    started from (home:checkall / home:checklinks) - the step immediately before - not the top-level
    Check menu, so Back always unwinds one step at a time like everywhere else."""
    target = "home:checklinks" if links else "home:checkall"
    return InlineKeyboardMarkup(inline_keyboard=[[btn(t("hub_btn_back"), target)]])


async def _respond(message: Message, in_place: bool, text: str, kb=None) -> None:
    """Edit the message (hub, in place) or post a new one."""
    if in_place:
        await safe_edit_text(message, text, kb)
    else:
        await message.answer(text, reply_markup=kb)


async def _run_all(message: Message, force: bool, in_place: bool = False) -> None:
    """Check every scraped + favorite entity. From the hub the progress and summary edit the SAME
    message in place, with a Stop button while probing and a Back to the check menu on every end."""
    global _active_stop
    if not await acquire_job():
        await _respond(message, in_place, t("check_busy"), _back_to_check())
        return
    stop_event = asyncio.Event()
    _active_stop = stop_event
    try:
        try:
            client = await get_scrape_client()
        except RuntimeError as e:
            await _respond(message, in_place, t("check_unavailable", reason=escape(str(e))), _back_to_check())
            return

        pool = get_pool()
        targets = sort_targets(await gather_targets(pool))
        if not targets:
            await _respond(message, in_place, t("check_nothing"), _back_to_check())
            return

        await cooldown_wait()
        stop_kb = _stop_kb()
        if in_place:
            status_msg = message
            await safe_edit_text(status_msg, t("check_started"), stop_kb)
        else:
            status_msg = await message.answer(t("check_started"), reply_markup=stop_kb)

        last_edit = 0

        async def progress(done: int, total: int) -> None:
            nonlocal last_edit
            if done - last_edit >= _PROGRESS_EVERY or done == total:
                last_edit = done
                try:
                    await status_msg.edit_text(t("check_progress", done=done, total=total), reply_markup=stop_kb)
                except TelegramBadRequest:
                    pass

        run = await run_check_all(client, targets, force=force, on_progress=progress, should_stop=stop_event.is_set)
        text, keyboard = await check_view.summary(pool)
        if run.stopped:
            text += t("check_stopped_note")
        if run.aborted:
            text += t("check_aborted_note", wait=format_wait(run.wait_seconds))
        if run.capped:
            text += t("check_capped_note", n=run.remaining)
        await safe_edit_text(status_msg, text, keyboard)
    finally:
        _active_stop = None
        release_job()


async def _run_link_check(message: Message, force: bool, in_place: bool = False) -> None:
    """Check Links: probe every archived link's target (reachable/dead), then show a summary with a
    confirm-guarded 'remove inactive links'. Same Stop button, 24h-cache and FloodWait handling as
    Check All."""
    global _active_stop
    if not await acquire_job():
        await _respond(message, in_place, t("check_busy"), _back_to_check(links=True))
        return
    stop_event = asyncio.Event()
    _active_stop = stop_event
    try:
        try:
            client = await get_scrape_client()
        except RuntimeError as e:
            await _respond(message, in_place, t("check_unavailable", reason=escape(str(e))), _back_to_check(links=True))
            return

        pool = get_pool()
        targets = await gather_link_targets(pool)
        if not targets:
            await _respond(message, in_place, t("check_links_nothing"), _back_to_check(links=True))
            return

        await cooldown_wait()
        stop_kb = _stop_kb()
        if in_place:
            status_msg = message
            await safe_edit_text(status_msg, t("check_started"), stop_kb)
        else:
            status_msg = await message.answer(t("check_started"), reply_markup=stop_kb)

        last_edit = 0

        async def progress(done: int, total: int) -> None:
            nonlocal last_edit
            if done - last_edit >= _PROGRESS_EVERY or done == total:
                last_edit = done
                try:
                    await status_msg.edit_text(t("check_progress", done=done, total=total), reply_markup=stop_kb)
                except TelegramBadRequest:
                    pass

        run = await run_check_all(client, targets, force=force, on_progress=progress, should_stop=stop_event.is_set)
        text, keyboard = await check_view.summary(pool, links=True)
        if run.stopped:
            text += t("check_stopped_note")
        if run.aborted:
            text += t("check_aborted_note", wait=format_wait(run.wait_seconds))
        if run.capped:
            text += t("check_capped_note", n=run.remaining)
        await safe_edit_text(status_msg, text, keyboard)
    finally:
        _active_stop = None
        release_job()


# --- run choice (from the pre-check options screen) ---------------------------------------------

@router.callback_query(F.data.startswith("chkrun:"))
async def on_check_run(callback: CallbackQuery) -> None:
    """Start the check chosen on the options screen. which: a=all / l=links; mode: f=full re-check
    (force) / s=skip the fresh (<24h) ones. Both still show every result in the summary."""
    _, which, mode = callback.data.split(":")
    await safe_answer(callback)
    force = mode == "f"
    if which == "l":
        await _run_link_check(callback.message, force, in_place=True)
    else:
        await _run_all(callback.message, force, in_place=True)


@router.callback_query(F.data.startswith("chksum:"))
async def on_check_summary(callback: CallbackQuery) -> None:
    """Show the last stored summary without re-checking (the options screen's 'Last summary')."""
    which = callback.data.split(":")[1]
    await safe_answer(callback)
    text, keyboard = await check_view.summary(get_pool(), links=which == "l")
    await safe_edit_text(callback.message, text, keyboard)


# --- stop + drill-down + removal callbacks ------------------------------------------------------


@router.callback_query(F.data == "chkstop")
async def on_check_stop(callback: CallbackQuery) -> None:
    """Stop button on a running Check All / Check Links: signal the probe loop to end. It saves
    everything checked so far, then _run_all/_run_link_check shows the partial summary (which carries
    its own Back to the check menu). If nothing is running the tap is just acknowledged."""
    if _active_stop is not None:
        _active_stop.set()
    await safe_answer(callback, t("check_stopping"))


@router.callback_query(F.data.startswith("chk:"))
async def on_list(callback: CallbackQuery) -> None:
    _, which, page = callback.data.split(":")
    await safe_answer(callback)
    pool = get_pool()
    if which == "s":  # back to the summary
        text, keyboard = await check_view.summary(pool)
        await safe_edit_text(callback.message, text, keyboard)
        return
    view = await check_view.list_view(pool, which, int(page))
    if view is None:
        await safe_edit_text(callback.message, t("check_gone"), None)
        return
    text, keyboard = view
    await safe_edit_text(callback.message, text, keyboard)


@router.callback_query(F.data.startswith("chkrm:"))
async def on_remove_ask(callback: CallbackQuery) -> None:
    which = callback.data.split(":")[1]
    await safe_answer(callback)
    view = await check_view.remove_confirm_view(get_pool(), which)
    if view is None:
        await safe_edit_text(callback.message, t("check_remove_none"), None)
        return
    text, keyboard = view
    await safe_edit_text(callback.message, text, keyboard)


@router.callback_query(F.data.startswith("chkrmy:"))
async def on_remove_confirm(callback: CallbackQuery) -> None:
    which = callback.data.split(":")[1]
    await safe_answer(callback)
    pool = get_pool()
    n, removed = await remove_inactive(pool, {_REMOVE_KIND[which]})
    header = t("check_removed", n=n, word=plural(n, "entity", "entities"))
    # Drop just-removed keys from this render: DB-backed ones are pruned by the watcher a beat later.
    view = await check_view.list_view(pool, which, 0, exclude=removed)
    if view is None:
        await safe_edit_text(callback.message, header, None)
        return
    text, keyboard = view
    await safe_edit_text(callback.message, f"{header}\n\n{text}", keyboard)


# --- Check Links drill-down: same per-kind lists as Check All, on the archived links -------------

@router.callback_query(F.data.startswith("lchk:"))
async def on_link_list(callback: CallbackQuery) -> None:
    _, which, page = callback.data.split(":")
    await safe_answer(callback)
    pool = get_pool()
    if which == "s":  # back to the link summary
        text, keyboard = await check_view.summary(pool, links=True)
        await safe_edit_text(callback.message, text, keyboard)
        return
    view = await check_view.list_view(pool, which, int(page), links=True)
    if view is None:
        await safe_edit_text(callback.message, t("check_gone"), None)
        return
    text, keyboard = view
    await safe_edit_text(callback.message, text, keyboard)


@router.callback_query(F.data.startswith("lchkrm:"))
async def on_link_remove_ask(callback: CallbackQuery) -> None:
    which = callback.data.split(":")[1]
    await safe_answer(callback)
    view = await check_view.remove_confirm_view(get_pool(), which, links=True)
    if view is None:
        await safe_edit_text(callback.message, t("check_remove_none"), None)
        return
    text, keyboard = view
    await safe_edit_text(callback.message, text, keyboard)


@router.callback_query(F.data.startswith("lchkrmy:"))
async def on_link_remove_confirm(callback: CallbackQuery) -> None:
    which = callback.data.split(":")[1]
    await safe_answer(callback)
    pool = get_pool()
    n, _rows, removed = await remove_inactive_links(pool, {_REMOVE_KIND[which]})
    header = t("check_links_removed", n=n, word=plural(n, "link", "links"))
    # Drop just-removed keys from this render; the watcher prunes the DB rows a beat later.
    view = await check_view.list_view(pool, which, 0, links=True, exclude=removed)
    if view is None:
        await safe_edit_text(callback.message, header, None)
        return
    text, keyboard = view
    await safe_edit_text(callback.message, f"{header}\n\n{text}", keyboard)
