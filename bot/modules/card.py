"""Entity card — paste a @username / t.me link / id, or forward a channel post, and get a card with
the actions that apply (check, favorite, and in-place drill-downs to members/links).

A pure launcher over the existing flows: it never writes the DB directly. The catch-all message
handler is filtered to non-command text (and channel forwards), so it can never shadow a command.
"""
import asyncio
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from telethon.errors import FloodWaitError

from bot import card, card_view, favorites_store
from bot.entitykind import BOT, CHANNEL, GROUP, USER
from bot.favorites import RateLimited, TelegramLookupUnavailable
from bot.group_links import canonical_group_key
from bot.hub_state import HubInput
from bot.i18n import t
from bot.job_lock import acquire_job, cooldown_wait, release_job
from bot.log import log
from bot.pagination import safe_answer, safe_edit_text
from bot.telethon_client import get_scrape_client
from collectors.check import check_and_store
from collectors.csv_import import find_group_csv_files, remove_registered_member, write_registered, write_registered_member
from collectors.resolve import invite_hash
from collectors.throttle import floodwait_seconds, format_wait
from db.pool import get_pool

router = Router(name="card")

# How long to wait for the watcher to import a just-written registered CSV before refreshing the card.
_IMPORT_REFRESH_DELAY = 2.0


def _is_entry(message: Message) -> bool:
    """A message the card should handle: a channel forward, or any non-command text. Commands start
    with '/' and are excluded here, so this never intercepts them regardless of router order."""
    if message.forward_from_chat is not None:
        return True
    text = message.text
    return bool(text) and not text.startswith("/")


def _ref_from_message(message: Message) -> str | None:
    chat = message.forward_from_chat
    if chat is not None:
        return f"@{chat.username}" if chat.username else str(chat.id)
    return card.parse_entity_ref(message.text)


def _text_not_command(message: Message) -> bool:
    return bool(message.text) and not message.text.startswith("/")


# Registered BEFORE on_entry so, while a hub prompt is active, the typed text is handled here instead
# of opening a card. When no state is set, the state filter fails and on_entry takes over.
@router.message(HubInput.waiting, _text_not_command)
async def on_hub_input(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    mode = data.get("mode", "groups")
    chat_id, msg_id = data.get("chat_id"), data.get("msg_id")
    query = (message.text or "").strip()
    try:
        await message.delete()  # hide the typed query; the hub message becomes the result
    except TelegramBadRequest:
        pass

    # Scrape prompts (sc_members/sc_messages/sc_links) ONLY scrape - never open a card - and show the
    # result + Back in the hub message.
    if mode.startswith("sc_") and chat_id and msg_id:
        from bot.modules.start import _BACK_TO_SCRAPE, run_scrape_inplace
        kind = mode[len("sc_"):]
        await run_scrape_inplace(message.bot, chat_id, msg_id, query, kind, _BACK_TO_SCRAPE[kind])
        return

    from bot.modules.start import search_results
    from bot.pagination import store_token
    text, keyboard = await search_results(mode, query, store_token(query), 0, msg_id or 0)
    if chat_id and msg_id:
        try:
            await message.bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, reply_markup=keyboard)
            return
        except TelegramBadRequest:
            pass
    await message.answer(text, reply_markup=keyboard)


@router.message(_is_entry)
async def on_entry(message: Message) -> None:
    ref = _ref_from_message(message)
    if ref is None:
        await _hub_reply(message, t("card_hint"), _back_home_kb())
        return
    pool = get_pool()
    try:
        target = await card.resolve_identity(pool, ref)
    except RateLimited as e:
        await _hub_reply(message, t("floodwait_notice", wait=format_wait(e.seconds)), _back_home_kb())
        return
    except TelegramLookupUnavailable as e:
        # The client is off (not authorized yet) and this entity isn't archived - that's the real
        # reason, not "not found": some cards (new links) NEED a live check to open at all.
        await _hub_reply(message, t("check_unavailable", reason=escape(str(e))), _back_home_kb())
        return
    if target is None:
        # A private invite that didn't resolve almost always means the SCRAPING account isn't a member
        # (or the link was revoked) - say so, instead of a generic "not found". Literal t() keys so the
        # i18n dead-key scanner sees both.
        if invite_hash(ref):
            await _hub_reply(message, t("card_invite_unresolved", q=escape(ref)), _back_home_kb())
        else:
            await _hub_reply(message, t("card_not_found", q=escape(ref)), _back_home_kb())
        return
    await _send_card(message, pool, target)


def _back_home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t("hub_btn_back"), callback_data="home:home")]])


async def _hub_reply(message: Message, text: str, keyboard) -> None:
    """Show a pasted entity's card IN PLACE of the hub menu (edit the tracked hub message + hide the
    pasted text), with a permanent Back to the menu. Falls back to a new message if there's no hub
    message to edit (e.g. the user pasted before ever opening /start)."""
    from bot.modules.start import hub_message_id

    hub_id = hub_message_id(message.chat.id)
    if hub_id is not None:
        try:
            await message.bot.edit_message_text(text, chat_id=message.chat.id, message_id=hub_id, reply_markup=keyboard)
            try:
                await message.delete()
            except TelegramBadRequest:
                pass
            return
        except TelegramBadRequest:
            pass  # the hub message is gone/stale -> post a new card instead
    await message.answer(text, reply_markup=keyboard)


async def _send_card(message: Message, pool, target) -> None:
    state = await card.archive_state(pool, target)
    token = card.pack_token(target, "home:home")           # the card's Back returns to the menu
    text, keyboard = card_view.render_card(target, state, token, "home:home")
    await _hub_reply(message, text, keyboard)


async def _edit_card(message: Message, pool, target, token: str) -> None:
    state = await card.archive_state(pool, target)
    text, keyboard = card_view.render_card(target, state, token, card.back_of(token))
    await safe_edit_text(message, text, keyboard)


@router.callback_query(F.data.startswith("cd:"))
async def on_card_action(callback: CallbackQuery) -> None:
    parts = callback.data.split(":")
    verb, token = parts[1], parts[2]

    target = card.unpack_token(token)
    if target is None:
        await safe_answer(callback)
        await safe_edit_text(callback.message, t("card_expired"), _back_home_kb())
        return

    if verb == "chk":
        await _do_check(callback, target, token)
        return
    if verb == "fav":
        await _do_favorite(callback, target, token)
        return
    if verb == "add":
        await _do_add(callback, target, token)
        return
    if verb == "scr":
        await _open_scrape(callback, target, token)
        return
    if verb == "sc":
        limit = int(parts[4]) if len(parts) > 4 else None
        await _scrape_dispatch(callback, target, token, parts[3], limit)
        return
    if verb == "exp":
        await _do_export(callback, target, token)
        return
    if verb == "del":
        await safe_answer(callback)
        text, keyboard = card_view.delete_confirm(target, token)
        await safe_edit_text(callback.message, text, keyboard)
        return
    if verb == "dely":
        await _do_delete(callback, target, token)
        return

    await safe_answer(callback)
    pool = get_pool()
    if verb == "crd":
        await _edit_card(callback.message, pool, target, token)
        return

    state = await card.archive_state(pool, target)
    page = int(parts[3]) if len(parts) > 3 else 0
    msgid = callback.message.message_id  # so names inside the drill open cards editing THIS message
    if verb == "mem":
        view = await card_view.render_members(pool, state, token, page, msgid)
    elif verb == "lnk":
        view = await card_view.render_links(pool, state, token, page, msgid)
    else:  # usr
        view = await card_view.render_user(pool, target, token, msgid=msgid)

    if view is None:  # the data is gone - fall back to the (refreshed) card
        await _edit_card(callback.message, pool, target, token)
        return
    text, keyboard = view
    await safe_edit_text(callback.message, text, keyboard)


def _ident(target) -> str:
    """A short label for an entity, for the action log."""
    return card.target_resolve_input(target) or target.title or (str(target.tg_id) if target.tg_id is not None else "?")


async def _do_check(callback: CallbackQuery, target, token: str) -> None:
    resolve_input = card.target_resolve_input(target)
    if resolve_input is None:
        await safe_answer(callback, t("card_check_cant"))
        return
    if not await acquire_job():
        await safe_answer(callback, t("check_busy"), show_alert=True)
        return
    # Answer the callback query NOW, before any network call: Telegram invalidates a callback query
    # after a short window, and check_and_store can run long (cooldown_wait, a live resolve + read
    # probe, and Telethon can silently sleep off a FloodWait under FLOOD_SLEEP_THRESHOLD inside the
    # call) - answering late here raises "query is too old" and crashes the update. The outcome
    # is shown via the card message itself (_edit_card below), not a toast.
    await safe_answer(callback)
    try:
        try:
            client = await get_scrape_client()
        except RuntimeError as e:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t("hub_btn_back"), callback_data=f"cd:crd:{token}")]])
            await safe_edit_text(callback.message, t("check_unavailable", reason=escape(str(e))), kb)
            return
        await cooldown_wait()
        try:
            await check_and_store(client, resolve_input, force=True)  # card Check always re-probes
        except FloodWaitError as e:
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t("hub_btn_back"), callback_data=f"cd:crd:{token}")]])
            await safe_edit_text(callback.message, t("floodwait_notice", wait=format_wait(floodwait_seconds(e))), kb)
            return
    finally:
        release_job()
    log(f"🔎 Check: {resolve_input}")
    await _edit_card(callback.message, get_pool(), target, token)


async def _do_favorite(callback: CallbackQuery, target, token: str) -> None:
    pool = get_pool()
    state = await card.archive_state(pool, target)
    if state.is_favorite:
        favorites_store.remove(target.username, target.tg_id, target.link)
        log(f"☆ Unfavorite: {_ident(target)}")
        await safe_answer(callback, t("card_unfav_toast"))
    else:
        favorites_store.add(target)
        log(f"⭐ Favorite: {_ident(target)}")
        await safe_answer(callback, t("card_fav_toast"))
    await _edit_card(callback.message, pool, target, token)


async def _do_add(callback: CallbackQuery, target, token: str) -> None:
    """Add an entity to the archive WITHOUT scraping: write a 'registered' CSV; the watcher then creates
    the (memberless) group or the (group-less) user/bot. No direct DB write - the watcher stays the sole
    writer. A user/bot needs a real tg id (from the live resolve) to register."""
    if target.kind in (USER, BOT):
        if target.tg_id is None:
            await safe_answer(callback, t("card_add_cant"))
            return
        write_registered_member(target.tg_id, target.username)
        log(f"➕ Add to archive (no scrape): {_ident(target)} [{target.kind}]")
    elif target.kind in (GROUP, CHANNEL):
        invite_input = card.target_resolve_input(target) or (target.title or "")
        write_registered(invite_input, target.title or invite_input, target.kind)
        log(f"➕ Add to archive (no scrape): {target.title or invite_input} [{target.kind}]")
    else:
        await safe_answer(callback, t("card_add_cant"))
        return
    await safe_answer(callback, t("card_added_toast"))
    await asyncio.sleep(_IMPORT_REFRESH_DELAY)  # let the watcher import it, then show it as archived
    await _edit_card(callback.message, get_pool(), target, token)


async def _open_scrape(callback: CallbackQuery, target, token: str) -> None:
    await safe_answer(callback)
    if target.kind == CHANNEL:  # a channel can only be link-scraped -> straight to the limit picker
        text, keyboard = card_view.limit_menu(target, token, "lnk")
    else:
        text, keyboard = card_view.scrape_menu(target, token)
    await safe_edit_text(callback.message, text, keyboard)


async def _scrape_dispatch(callback: CallbackQuery, target, token: str, what: str, limit: int | None) -> None:
    if what == "m":  # members: no message limit
        await _run_scrape(callback, target, token, "members", None)
        return
    if limit is None:  # messages/links: ask how many first
        await safe_answer(callback)
        text, keyboard = card_view.limit_menu(target, token, what)
        await safe_edit_text(callback.message, text, keyboard)
        return
    await _run_scrape(callback, target, token, "messages" if what == "msg" else "links", limit)


async def _run_scrape(callback: CallbackQuery, target, token: str, kind: str, limit: int | None) -> None:
    """Scrape from the card IN PLACE (same engine as the hub), editing the card message with the
    result + a Back that returns to the card. No new message."""
    from bot.modules.start import run_scrape_inplace

    group_input = card.target_resolve_input(target)
    if group_input is None:
        await safe_answer(callback, t("card_check_cant"))
        return
    await safe_answer(callback)
    raw = f"{group_input} {limit}" if limit else group_input
    await run_scrape_inplace(
        callback.message.bot, callback.message.chat.id, callback.message.message_id, raw, kind, f"cd:crd:{token}",
    )


async def _do_export(callback: CallbackQuery, target, token: str) -> None:
    from bot.modules.admin import send_group_export

    await safe_answer(callback)
    pool = get_pool()
    state = await card.archive_state(pool, target)
    sent = state.group_id is not None and await send_group_export(callback.message, state.group_id, target.title or "")
    if sent:
        log(f"📤 Export: {_ident(target)}")
        return
    # Nothing to export: edit the card message in place with a Back to the card, don't post a new one.
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t("hub_btn_back"), callback_data=f"cd:crd:{token}")]])
    await safe_edit_text(callback.message, t("card_export_empty"), kb)


async def _do_delete(callback: CallbackQuery, target, token: str) -> None:
    """Remove the entity's CSVs; the watcher prunes the DB. For a group/channel that's its member/link
    CSVs + registration; for a standalone user/bot it's the registered-member CSV (un-register). No
    direct DB write - the watcher stays the sole writer."""
    if target.kind in (USER, BOT):
        n = remove_registered_member(target.tg_id, target.username)
        log(f"🗑 Un-register: {_ident(target)} ({n} file(s))")
    else:
        canonical = canonical_group_key(target.title or "", target.username, target.link)
        files = find_group_csv_files(canonical, target.title or "", which="all")
        for file in files:
            try:
                file.unlink()
            except OSError as e:
                log(f"⚠️ card delete: couldn't remove {file}: {e}")
        log(f"🗑 Delete: {_ident(target)} ({len(files)} file(s))")
    await safe_answer(callback, t("card_deleted_toast"))
    await asyncio.sleep(_IMPORT_REFRESH_DELAY)  # let the watcher prune, then refresh
    await _edit_card(callback.message, get_pool(), target, token)
