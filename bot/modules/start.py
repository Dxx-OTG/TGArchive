import json
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot import card, card_view
from bot.favorites import RateLimited, TelegramLookupUnavailable
from bot.group_links import group_link
from bot.hub_state import HubInput
from bot.inplace import card_link, inplace_link as _inplace_link, linker as _linker, sharers_linker as _sharers_linker
from bot.i18n import plural, t
from bot.log import log
from bot.modules import groups as groups_mod
from bot.modules import stats as stats_mod
from bot.pagination import btn as _btn, get_token, nav_row, page_line, paginate, safe_answer, safe_edit_text, store_token
from collectors.throttle import format_wait
from db.pool import get_pool
from db.queries import groups as groups_q
from db.queries import links as links_q
from db.queries import members as members_q

# Rows per page in every hub list, one uniform value. Telegram caps a message at ~100 formatting
# entities and each clickable link is one; group/channel rows carry up to 3 links (name + 👥 + 🔗), so
# 30/page keeps EVERY link clickable (30 * 3 = 90 < 100) on every page.
_HUB_PER_PAGE = 30

router = Router(name="start")

# The hub message we can edit in place, per chat, so a pasted @username/link REPLACES the menu (with a
# Back to it) instead of posting a new message. Updated whenever the home menu is shown; a stale id
# just means the edit fails and we fall back to a new message. In-memory (fine: the hub is re-shown by
# /start on restart).
_hub_messages: dict[int, int] = {}


def note_hub_message(chat_id: int, msg_id: int) -> None:
    _hub_messages[chat_id] = msg_id


def hub_message_id(chat_id: int) -> int | None:
    return _hub_messages.get(chat_id)


# --- /start hub: the primary, command-free menu, navigated in place (no new messages) ------------

def _back(target: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_btn(t("hub_btn_back"), target)]])


def home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [_btn(t("home_btn_scrape"), "home:scrape"), _btn(t("home_btn_search"), "home:search"), _btn(t("home_btn_browse"), "home:browse")],
        [_btn(t("home_btn_data"), "home:data"), _btn(t("home_btn_favorites"), "home:favs"), _btn(t("home_btn_help"), "home:help")],
    ])


def hub_home() -> tuple[str, InlineKeyboardMarkup]:
    return t("hub_home"), home_keyboard()


def _browse_menu() -> tuple[str, InlineKeyboardMarkup]:
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn(t("hub_btn_groups"), "home:grp:0"), _btn(t("hub_btn_channels"), "home:chn:0")],
        [_btn(t("hub_btn_users"), "home:usr:0"), _btn(t("hub_btn_bots"), "home:bot:0")],
        [_btn(t("hub_btn_links"), "home:lnk:0")],
        [_btn(t("hub_btn_back"), "home:home")],
    ])
    return t("hub_browse"), kb


def _data_menu() -> tuple[str, InlineKeyboardMarkup]:
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn(t("hub_btn_stats"), "home:stats"), _btn(t("home_btn_check"), "home:check")],
        [_btn(t("hub_btn_export_all"), "home:expall"), _btn(t("hub_btn_delete_all"), "home:delall")],
        [_btn(t("hub_btn_back"), "home:home")],
    ])
    return t("hub_data"), kb


def _check_menu() -> tuple[str, InlineKeyboardMarkup]:
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn(t("hub_btn_check_all"), "home:checkall")],
        [_btn(t("hub_btn_check_links"), "home:checklinks")],
        [_btn(t("hub_btn_back"), "home:data")],
    ])
    return t("hub_check"), kb


def _help_view(it: bool = False) -> tuple[str, InlineKeyboardMarkup]:
    # Same guide in both languages: one button toggles EN<->IT, Back returns to the hub.
    if it:
        toggle = _btn(t("hub_help_btn_en"), "home:help")
        text = t("hub_help_it")
    else:
        toggle = _btn(t("hub_help_btn_it"), "home:helpit")
        text = t("hub_help")
    kb = InlineKeyboardMarkup(inline_keyboard=[[toggle], [_btn(t("hub_btn_back"), "home:home")]])
    return text, kb


def _search_menu() -> tuple[str, InlineKeyboardMarkup]:
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn(t("hub_btn_users"), "home:su"), _btn(t("hub_btn_bots"), "home:sb")],
        [_btn(t("hub_btn_groups"), "home:sg"), _btn(t("hub_btn_channels"), "home:sc")],
        [_btn(t("hub_btn_links"), "home:sl")],
        [_btn(t("hub_btn_back"), "home:home")],
    ])
    return t("hub_search"), kb


def _scrape_menu() -> tuple[str, InlineKeyboardMarkup]:
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [_btn(t("card_btn_scr_members"), "home:scm"), _btn(t("card_btn_scr_messages"), "home:scms"), _btn(t("card_btn_scr_links"), "home:scl")],
        [_btn(t("hub_btn_back"), "home:home")],
    ])
    return t("hub_scrape"), kb


async def _prompt(m: Message, state: FSMContext, mode: str, text: str, back: str) -> None:
    """Open a text prompt: remember what we're waiting for + which message to edit with the result,
    then wait for the user's next message (handled in bot/modules/card.py). `back` is where the
    prompt's Back goes (the search or scrape menu)."""
    await state.set_state(HubInput.waiting)
    await state.update_data(mode=mode, chat_id=m.chat.id, msg_id=m.message_id)
    kb = InlineKeyboardMarkup(inline_keyboard=[[_btn(t("hub_btn_back"), back)]])
    await safe_edit_text(m, text, kb)


# Back from a results view -> the prompt for that kind (a new search); from the prompt -> the search
# menu; from the menu -> home. That's the back-stack the user walks with the single Back button.
_BACK_TO_PROMPT = {"users": "home:su", "bots": "home:sb", "groups": "home:sg", "channels": "home:sc", "links": "home:sl"}


def _with_back(kb: InlineKeyboardMarkup | None, mode: str) -> InlineKeyboardMarkup:
    rows = list(kb.inline_keyboard) if kb else []
    rows.append([_btn(t("hub_btn_back"), _BACK_TO_PROMPT[mode])])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def search_results(mode: str, query: str, token: str, page: int, msgid: int) -> tuple[str, InlineKeyboardMarkup]:
    """(text, keyboard) for a hub search result page, ALWAYS with a Back button (even on no results).
    Hub-owned pagination (`hsr:`) so Back survives page turns. Reuses the search data + renderers."""
    from bot.modules import search_groups as sg
    from bot.modules import search_users as su
    from bot.querykind import QueryKind, classify_query
    from db.queries import groups as groups_q

    pool = get_pool()
    if mode in ("users", "bots"):
        people = await su._fetch_people(pool, query, bots=(mode == "bots"))
        if not people:
            return t("searchusers_no_result", query=escape(query)), _with_back(None, mode)
        return _user_list_view(people, query, f"hsr:{mode}:{token}", page, _BACK_TO_PROMPT[mode], msgid, bots=(mode == "bots"))

    if mode == "links":
        found = await links_q.search_links(pool, query)
        if not found:
            return t("searchlinks_no_result", query=escape(query)), _with_back(None, mode)
        return _link_list_view(found, query, f"hsr:{mode}:{token}", page, _BACK_TO_PROMPT[mode], msgid)

    db_kind = "channel" if mode == "channels" else "group"
    kind, value = classify_query(query)
    if kind is QueryKind.USERNAME:
        group = await groups_q.find_group_by_exact_username(pool, value, kind=db_kind)
        items = [group] if group else []
    else:
        items = await sg._search(pool, query, db_kind)
    if not items:
        return t("searchgroups_no_group_found", query=escape(query)), _with_back(None, mode)
    legend = t("channels_list_legend") if db_kind == "channel" else t("groups_list_legend")
    return _group_list_view(items, sg._header(query, len(items)), legend, f"hsr:{mode}:{token}", page, _BACK_TO_PROMPT[mode], msgid)


# Scrape back-stack: summary -> the prompt for that kind (new scrape) -> the scrape menu -> home.
_BACK_TO_SCRAPE = {"members": "home:scm", "messages": "home:scms", "links": "home:scl"}


def _scrape_summary(kind: str, result: dict, name: str) -> str:
    """`name` is the already-escaped entity name to show in the summary."""
    if kind == "members":
        return t("hub_scrape_done_members", title=name, new_added=result["new_added"])
    if kind == "messages":
        return t("hub_scrape_done_messages", title=name, new_added=result["new_added"], messages_read=result["messages_read"])
    return t("hub_scrape_done_links", title=name, links_saved=result["links_saved"], links_dup=result["links_dup"])


def _scrape_fail_text(group: str, err) -> str:
    """Map a typed ScrapeError to the exact user-facing reason (not found / wrong type / rate-limited /
    empty), so a failed scrape says WHY instead of one generic message."""
    from collectors.scrape_errors import NOT_FOUND, NOT_MEMBER, RATE_LIMITED, WRONG_TYPE
    from collectors.throttle import format_wait
    g = escape(group)
    if err.reason == NOT_FOUND:
        return t("scrape_fail_not_found", group=g)
    if err.reason == NOT_MEMBER:
        return t("scrape_fail_not_member", group=g)
    if err.reason == WRONG_TYPE:
        return t("scrape_fail_wrong_type", group=g, kind=escape(err.detail or "channel"))
    if err.reason == RATE_LIMITED:
        secs = int(err.detail) if (err.detail or "").isdigit() else None
        return t("scrape_fail_rate_limited", wait=format_wait(secs))
    return t("scrape_fail_empty", group=g)


async def run_scrape_inplace(bot, chat_id: int, msg_id: int, raw_input: str, kind: str, back_cb: str) -> None:
    """Scrape (members/messages/links) and show the result + Back IN the message (edited by id). Used
    by both the hub scrape (Back -> scrape menu) and the card's Re-scrape (Back -> the card).
    For messages/links a trailing number in the input sets how many messages to read (default 500,
    capped at MAX_LIMIT); members has no limit. Reuses the shared job lock, the `<group> [limit]`
    parser and the scrapers (which self-validate the entity type). Only-scrape: never opens a card."""
    from bot.job_lock import acquire_job, cooldown_wait, release_job
    from bot.modules.scrape import _split_group_and_limit
    from bot.telethon_client import get_scrape_client
    from collectors.scrape_errors import ScrapeError
    from CLI.ExtractLinks import DEFAULT_LIMIT as LINK_DEF, MAX_LIMIT as LINK_MAX, extract_links
    from CLI.Messages import DEFAULT_LIMIT as MSG_DEF, MAX_LIMIT as MSG_MAX, scrape_from_messages
    from CLI.Scrape import extract_members

    if kind == "members":
        group_input, limit = raw_input, 0
    elif kind == "messages":
        group_input, limit = _split_group_and_limit(raw_input, MSG_DEF, MSG_MAX)
    else:
        group_input, limit = _split_group_and_limit(raw_input, LINK_DEF, LINK_MAX)

    back = InlineKeyboardMarkup(inline_keyboard=[[_btn(t("hub_btn_back"), back_cb)]])

    async def edit(text: str, kb: InlineKeyboardMarkup | None = back) -> None:
        try:
            await bot.edit_message_text(text, chat_id=chat_id, message_id=msg_id, reply_markup=kb)
        except TelegramBadRequest:
            pass

    if not await acquire_job():
        await edit(t("scrape_busy"))
        return
    try:
        try:
            client = await get_scrape_client()
        except RuntimeError as e:
            await edit(t("scrape_unavailable", reason=escape(str(e))))
            return
        await cooldown_wait()
        await edit(t("scrape_started", group=escape(group_input)), None)
        try:
            if kind == "members":
                result = await extract_members(client, group_input)
            elif kind == "messages":
                result = await scrape_from_messages(client, group_input, limit)
            else:
                result = await extract_links(client, group_input, limit)
        except ScrapeError as e:
            if e.__cause__ is not None:  # the real underlying error (e.g. why resolve failed)
                log(f"⚠️ scrape of '{group_input}' failed ({e.reason}): {type(e.__cause__).__name__}: {e.__cause__}")
            await edit(_scrape_fail_text(group_input, e))
            return
        except Exception as e:
            await edit(t("scrape_error", error=escape(str(e))))
            return
        if not result:  # safety net: the scrapers now raise ScrapeError instead of returning None
            await edit(t("hub_scrape_failed", group=escape(group_input)))
            return
        title = result["group_title"]
        log(f"🤖 Scrape {kind}: {group_input} -> {title}")
        # The name is clickable TEXT that opens its card IN PLACE (Back returns to back_cb).
        name = _inplace_link({"a": "c", "h": group_input, "msgid": msg_id, "back": back_cb}, escape(title))
        await edit(_scrape_summary(kind, result, name))
    finally:
        release_job()


@router.callback_query(F.data.startswith("hsr:"))
async def on_search_page(callback: CallbackQuery, state: FSMContext) -> None:
    _, mode, token, page = callback.data.split(":")
    await safe_answer(callback)
    await state.clear()
    query = get_token(token)
    if query is None:
        await safe_edit_text(callback.message, t("list_expired"), _with_back(None, mode))
        return
    text, keyboard = await search_results(mode, query, token, int(page), callback.message.message_id)
    await safe_edit_text(callback.message, text, keyboard)


@router.callback_query(F.data.startswith("hgm:"))
async def on_group_members(callback: CallbackQuery) -> None:
    _, gid, btok, page = callback.data.split(":")
    await safe_answer(callback)
    text, keyboard = await _group_members_view(int(gid), btok, int(page), callback.message.message_id)
    await safe_edit_text(callback.message, text, keyboard)


@router.callback_query(F.data.startswith("hgl:"))
async def on_group_links(callback: CallbackQuery) -> None:
    _, gid, btok, page = callback.data.split(":")
    await safe_answer(callback)
    text, keyboard = await _group_links_view(int(gid), btok, int(page), callback.message.message_id)
    await safe_edit_text(callback.message, text, keyboard)


@router.callback_query(F.data.startswith("iv:"))
async def on_inplace_reenter(callback: CallbackQuery) -> None:
    """Re-open an in-place deep-link view (user detail / sharers) by editing THIS message, so a Back
    from a card spawned inside it returns to it instead of skipping to the list it came from."""
    token = callback.data[len("iv:"):]
    raw = get_token(token)
    try:
        data = json.loads(raw) if raw else None
    except (json.JSONDecodeError, TypeError):
        data = None
    await safe_answer(callback)
    if not data:
        await safe_edit_text(callback.message, t("card_expired"), _back("home:home"))
        return
    data = {**data, "msgid": callback.message.message_id}  # edit the current message
    text, keyboard = await _inplace_view(data.get("a"), data)
    await safe_edit_text(callback.message, text, keyboard)


def _reentry(payload: dict) -> str:
    """A callback that RE-OPENS an in-place deep-link view (editing the current message) - so a card
    spawned inside it can Back INTO it instead of skipping to the list. Used for the views that have no
    natural pagination callback (user detail, sharers). `iv:<token>` -> on_inplace_reenter."""
    return f"iv:{store_token(json.dumps(payload))}"


async def _inplace_view(action: str, data: dict):
    """(text, keyboard) for a clickable-text deep link: a group's members/links, a user detail, a
    link's sharers, or an entity's card. `data['back']` is where the view's own Back returns."""
    back = data.get("back") or "home:home"
    btok = store_token(back)
    if action == "m":
        return await _group_members_view(data["gid"], btok, 0, data.get("msgid"))
    if action == "l":
        return await _group_links_view(data["gid"], btok, 0, data.get("msgid"))
    if action == "st":
        return await _stats_drill(data["w"], data["msgid"])
    if action == "sh":  # who shared this link (tapped the 👤 N count); spawned cards re-enter here
        reentry = _reentry({"a": "sh", "lk": data["lk"], "back": back})
        return await _link_sharers_view(data["lk"], data.get("msgid"), back, reentry)
    if action == "u":  # a person's groups+links list, in place; spawned cards re-enter here (not the list)
        try:
            target = await card.resolve_identity(get_pool(), data.get("h") or "")
        except RateLimited as e:
            return t("floodwait_notice", wait=format_wait(e.seconds)), _back(back)
        except TelegramLookupUnavailable as e:
            return t("check_unavailable", reason=escape(str(e))), _back(back)
        if target is None:
            return t("card_not_found", q=escape(data.get("h") or "?")), _back(back)
        reentry = _reentry({"a": "u", "h": data.get("h"), "back": back})
        view = await card_view.render_user(get_pool(), target, "", back_cb=back, msgid=data.get("msgid"), inner_back=reentry)
        return view if view is not None else await _inplace_view("c", data)
    # card
    try:
        target = await card.resolve_identity(get_pool(), data.get("h") or "")
    except RateLimited as e:
        return t("floodwait_notice", wait=format_wait(e.seconds)), _back(back)
    except TelegramLookupUnavailable as e:
        return t("check_unavailable", reason=escape(str(e))), _back(back)
    if target is None:
        return t("card_not_found", q=escape(data.get("h") or "?")), _back(back)
    state = await card.archive_state(get_pool(), target)
    return card_view.render_card(target, state, card.pack_token(target, back), back)


async def _stats_view(msgid: int) -> tuple[str, InlineKeyboardMarkup]:
    """The hub stats summary: each total is clickable TEXT that opens its list IN PLACE (editing this
    message), instead of the old deep link that posted a new message."""
    from bot.modules.admin import stats_counts

    c = await stats_counts(get_pool())

    def cl(w: str, n: int) -> str:
        return _inplace_link({"a": "st", "w": w, "msgid": msgid, "back": "home:stats"}, str(n)) if n else str(n)

    lines = [
        t("stats_header"),
        t("stats_groups", n=cl("g", c["groups"])),
        t("stats_channels", n=cl("c", c["channels"])),
        t("stats_links", n=cl("l", c["links"])),
        t("stats_users", n=cl("m", c["users"])),
        t("stats_with_username", n=cl("mw", c["with_username"])),
        t("stats_without_username", n=cl("mn", c["without_username"])),
        t("stats_bots", n=cl("mb", c["bots"])),
    ]
    return "\n".join(lines), _back("home:data")


async def _stats_members_view(which: str, page: int, msgid: int | None = None) -> tuple[str, InlineKeyboardMarkup]:
    rows = await members_q.list_members(get_pool(), which)  # blacklisted excluded in the query
    if not rows:
        return t("stats_no_members"), _back("home:stats")
    page_items, page, total_pages = paginate(rows, page)
    lines = [stats_mod._members_header(which, len(rows))]
    if pl := page_line(page, total_pages):
        lines.append(pl)
    lines.append("")
    ln = _linker(msgid, f"home:stm:{which}:{page}")
    lines.extend(card_view._member_line(r, ln) for r in page_items)
    nav = nav_row(f"home:stm:{which}", page, total_pages)
    kb = [nav] if nav else []
    kb.append([_btn(t("hub_btn_back"), "home:stats")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb)


async def _stats_links_view(page: int, msgid: int | None = None) -> tuple[str, InlineKeyboardMarkup]:
    rows = await links_q.list_all_links(get_pool())
    if not rows:
        return t("stats_no_links"), _back("home:stats")
    page_items, page, total_pages = paginate(rows, page, _HUB_PER_PAGE)
    lines = [t("stats_all_links_header", n=len(rows), word=plural(len(rows), "Link", "Links"))]
    if pl := page_line(page, total_pages):
        lines.append(pl)
    lines.append("")
    back = f"home:stl:{page}"
    lines.extend(card_view.link_lines_by_group(page_items, _linker(msgid, back), _sharers_linker(msgid, back)))
    nav = nav_row("home:stl", page, total_pages)
    kb = [nav] if nav else []
    kb.append([_btn(t("hub_btn_back"), "home:stats")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb)


async def _stats_drill(w: str, msgid: int):
    """A stats total tapped -> its list, in place, with Back to stats kept even across pagination.
    Groups/channels reuse the list rendering but with a stats-specific nav_prefix/parent_back."""
    if w == "g":
        return await _list_view("group", 0, msgid, "home:stg", "home:stats")
    if w == "c":
        return await _list_view("channel", 0, msgid, "home:stc", "home:stats")
    if w == "l":
        return await _stats_links_view(0, msgid)
    return await _stats_members_view({"m": "all", "mw": "with", "mn": "without", "mb": "bots"}[w], 0, msgid)


def _delete_all_confirm() -> tuple[str, InlineKeyboardMarkup]:
    # Reuses admin's "delall:yes" wipe handler (which edits this same message with the result).
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        _btn(t("hub_btn_delete_all_yes"), "delall:yes"),
        _btn(t("hub_btn_back"), "home:data"),
    ]])
    return t("hub_delall_confirm"), kb


# --- button-based group lists + in-place members/links/card (shared by browse and search) --------

def _group_name_html(group, msgid: int | None = None, back: str | None = None) -> str:
    """The group's name in a drill header. It opens the group's CARD in place (Back -> this drill),
    not the real chat - only the card itself links out. Plain text if there's no message to edit."""
    handle = group_link(group["username"], group["invite_input"]) or group["invite_input"] or (group["title"] or "")
    title = group["title"] or "?"
    if msgid is not None and handle:
        return card_link(handle, title, msgid, back)
    return escape(title)


def _hub_group_line(g, msgid: int, back_cb: str) -> str:
    """A group line, all clickable TEXT (no buttons): the name opens its card, the 👥/🔗 counts open
    its members/links - each in place, editing message `msgid`, with Back returning to `back_cb`."""
    handle = group_link(g["username"], g["invite_input"]) or g["invite_input"] or (g["title"] or "")
    title = escape(g["title"] or g["username"] or "?")
    name = _inplace_link({"a": "c", "h": handle, "msgid": msgid, "back": back_cb}, title)
    icon = "📢" if (g.get("kind") == "channel" and not g["members"]) else "📁"
    parts = []
    if g["members"]:
        parts.append(_inplace_link({"a": "m", "gid": g["id"], "msgid": msgid, "back": back_cb}, f"👥 {g['members']}"))
    if g["links"]:
        parts.append(_inplace_link({"a": "l", "gid": g["id"], "msgid": msgid, "back": back_cb}, f"🔗 {g['links']}"))
    line = f"{icon} {name}"
    if parts:
        line += " — " + " · ".join(parts)
    return line


def _group_list_view(items: list, header: str, legend: str, nav_prefix: str, page: int, parent_back: str, msgid: int):
    """(text, keyboard) for a page of the TEXT group list. The group name and the 👥/🔗 counts are
    clickable text (in-place deep links, editing `msgid`); only pagination and the list's own Back are
    buttons. `nav_prefix` paginates; `parent_back` is where the list's Back goes."""
    page_items, page, total_pages = paginate(items, page, _HUB_PER_PAGE)
    back_cb = f"{nav_prefix}:{page}"  # the drill-downs return to this exact list page
    lines = [header, legend]
    if pl := page_line(page, total_pages):
        lines.append(pl)
    lines.append("")
    lines.extend(_hub_group_line(g, msgid, back_cb) for g in page_items)
    rows = []
    if navr := nav_row(nav_prefix, page, total_pages):
        rows.append(navr)
    rows.append([_btn(t("hub_btn_back"), parent_back)])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def _list_view(kind: str, page: int, msgid: int, nav_prefix: str, parent_back: str) -> tuple[str, InlineKeyboardMarkup]:
    """The groups/channels list. Used by Browse (Back -> browse menu) and the Stats drill-down (Back
    -> stats), with different nav_prefix/parent_back so pagination keeps the right Back."""
    items = await groups_mod._load(get_pool(), kind)
    if not items:
        return (t("channels_list_empty") if kind == "channel" else t("groups_list_empty")), _back(parent_back)
    legend = t("channels_list_legend") if kind == "channel" else t("groups_list_legend")
    return _group_list_view(items, groups_mod._header(kind, len(items)), legend, nav_prefix, page, parent_back, msgid)


def _hub_user_line(p, msgid: int, back_cb: str, icon: str = "👤") -> str:
    """A person line: 👤 @name — 📁 groups · 🔗 links (🤖 for a bot). The @name opens the entity's card;
    the 📁 and 🔗 counts both open its groups/links list (`render_user` shows both), in place. That's up
    to 3 links/row: 30 rows = 90 entities, still under Telegram's ~100 formatting-entity cap - the reason
    `_HUB_PER_PAGE` is 30 (a bigger page would drop the last rows' links and glitch their emojis)."""
    uid = p["tg_user_id"]
    handle = f"@{p['username']}" if p["username"] else str(uid)
    label = escape(f"@{p['username']}" if p["username"] else f"#{uid}")
    name = _inplace_link({"a": "c", "h": handle, "msgid": msgid, "back": back_cb}, label)
    detail = {"a": "u", "h": handle, "msgid": msgid, "back": back_cb}
    parts = [_inplace_link(detail, f"📁 {p['num_groups']}")]
    if p["num_links"]:
        parts.append(_inplace_link(detail, f"🔗 {p['num_links']}"))
    return f"{icon} {name} — " + " · ".join(parts)


def _user_list_view(people: list, query: str, nav_prefix: str, page: int, parent_back: str, msgid: int, *, bots: bool = False):
    """Text list of matched users/bots (clickable -> their card), like the group list."""
    page_items, page, total_pages = paginate(people, page, _HUB_PER_PAGE)
    back_cb = f"{nav_prefix}:{page}"
    found = t("searchbots_found_text", n=len(people), word=plural(len(people), "Result", "Results"), query=escape(query)) if bots \
        else t("searchusers_found_text", n=len(people), word=plural(len(people), "Result", "Results"), query=escape(query))
    lines = [found, t("users_list_legend")]
    if pl := page_line(page, total_pages):
        lines.append(pl)
    lines.append("")
    lines.extend(_hub_user_line(p, msgid, back_cb, "🤖" if bots else "👤") for p in page_items)
    rows = []
    if navr := nav_row(nav_prefix, page, total_pages):
        rows.append(navr)
    rows.append([_btn(t("hub_btn_back"), parent_back)])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


def _link_list_view(links: list, query: str, nav_prefix: str, page: int, parent_back: str, msgid: int | None = None):
    """Text list of matched links: each is the clean name (no https://…) that opens that entity's CARD
    in place (Back -> this list). One link = one formatting entity, so a full 30-item page stays under
    Telegram's ~100 cap."""
    page_items, page, total_pages = paginate(links, page, _HUB_PER_PAGE)
    lines = [t("searchlinks_found_text", n=len(links), word=plural(len(links), "Link", "Links"), query=escape(query))]
    if pl := page_line(page, total_pages):
        lines.append(pl)
    lines.append("")
    back = f"{nav_prefix}:{page}"
    lines.extend(card_view.link_lines_by_group(page_items, _linker(msgid, back), _sharers_linker(msgid, back)))
    rows = []
    if navr := nav_row(nav_prefix, page, total_pages):
        rows.append(navr)
    rows.append([_btn(t("hub_btn_back"), parent_back)])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def _browse_people_view(page: int, msgid: int, *, bots: bool = False) -> tuple[str, InlineKeyboardMarkup]:
    """Browse -> Users (bots=False) or Bots (bots=True): every one, 30/page, name -> card and 📁/🔗
    counts -> their groups/links. Back -> the browse menu."""
    people = await members_q.list_people(get_pool(), bots=bots)
    prefix = "home:bot" if bots else "home:usr"
    if not people:
        return (t("bots_list_empty") if bots else t("users_list_empty")), _back("home:browse")
    page_items, page, total_pages = paginate(people, page, _HUB_PER_PAGE)
    back_cb = f"{prefix}:{page}"
    header = (t("bots_list_header", n=len(people), word=plural(len(people), "Bot", "Bots")) if bots
              else t("users_list_header", n=len(people), word=plural(len(people), "User", "Users")))
    icon = "🤖" if bots else "👤"
    lines = [header, t("users_list_legend")]
    if pl := page_line(page, total_pages):
        lines.append(pl)
    lines.append("")
    lines.extend(_hub_user_line(p, msgid, back_cb, icon) for p in page_items)
    rows = []
    if navr := nav_row(prefix, page, total_pages):
        rows.append(navr)
    rows.append([_btn(t("hub_btn_back"), "home:browse")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


async def _browse_links_view(page: int, msgid: int) -> tuple[str, InlineKeyboardMarkup]:
    """Browse -> Links: every extracted link, grouped by source group/channel (like the stats list),
    each with a clickable 👤 N = how many people shared it. Back -> the browse menu."""
    rows = await links_q.list_all_links(get_pool())
    if not rows:
        return t("links_list_empty"), _back("home:browse")
    page_items, page, total_pages = paginate(rows, page, _HUB_PER_PAGE)
    back = f"home:lnk:{page}"
    lines = [t("links_list_header", n=len(rows), word=plural(len(rows), "Link", "Links"))]
    if pl := page_line(page, total_pages):
        lines.append(pl)
    lines.append("")
    lines.extend(card_view.link_lines_by_group(page_items, _linker(msgid, back), _sharers_linker(msgid, back)))
    nav = nav_row("home:lnk", page, total_pages)
    kb = [nav] if nav else []
    kb.append([_btn(t("hub_btn_back"), "home:browse")])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb)


async def _link_sharers_view(key: str, msgid: int, back: str, self_back: str) -> tuple[str, InlineKeyboardMarkup]:
    """Who shared a given link (tapped its 👤 N). Each person opens their card in place, returning
    HERE (self_back, a re-entry callback); the view's own Back returns to the link list. Capped, not
    paginated (a link rarely has many distinct sharers)."""
    sharers = await members_q.link_sharers(get_pool(), key)
    if not sharers:
        return t("link_sharers_empty"), _back(back)
    lines = [t("link_sharers_header", n=len(sharers), word=plural(len(sharers), "Person", "People")), ""]
    for s in sharers[:_HUB_PER_PAGE]:
        handle = f"@{s['username']}" if s["username"] else str(s["tg_user_id"])
        label = f"@{s['username']}" if s["username"] else f"#{s['tg_user_id']}"
        lines.append(f"👤 {card_link(handle, label, msgid, self_back)}")
    if len(sharers) > _HUB_PER_PAGE:
        lines.append(t("list_more", n=len(sharers) - _HUB_PER_PAGE))
    return "\n".join(lines), _back(back)


async def _group_members_view(gid: int, btok: str, page: int, msgid: int | None = None):
    pool = get_pool()
    group = await groups_q.get_group_by_id(pool, gid)
    rows = await members_q.list_distinct_group_members(pool, gid) if group else []
    back = get_token(btok) or "home:browse"
    if not rows:
        return t("members_gone"), _back(back)
    page_items, page, total_pages = paginate(rows, page)
    self_back = f"hgm:{gid}:{btok}:{page}"  # a member's card (and the header) return to this page
    lines = [t("members_header", title=_group_name_html(group, msgid, self_back), n=len(rows), word=plural(len(rows), "Member", "Members"))]
    if pl := page_line(page, total_pages):
        lines.append(pl)
    lines.append("")
    ln = _linker(msgid, self_back)
    lines.extend(card_view._member_line(r, ln) for r in page_items)
    nav = nav_row(f"hgm:{gid}:{btok}", page, total_pages)
    kb = [nav] if nav else []
    kb.append([_btn(t("hub_btn_back"), back)])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb)


async def _group_links_view(gid: int, btok: str, page: int, msgid: int | None = None):
    pool = get_pool()
    group = await groups_q.get_group_by_id(pool, gid)
    rows = await links_q.links_for_group(pool, gid) if group else []
    back = get_token(btok) or "home:browse"
    if not rows:
        return t("links_gone"), _back(back)
    page_items, page, total_pages = paginate(rows, page, _HUB_PER_PAGE)
    self_back = f"hgl:{gid}:{btok}:{page}"  # a link's card (and the header) return to this page
    lines = [t("links_group_header", group=_group_name_html(group, msgid, self_back), n=len(rows), word=plural(len(rows), "Link", "Links"))]
    if pl := page_line(page, total_pages):
        lines.append(pl)
    lines.append("")
    ln = _linker(msgid, self_back)
    cl = _sharers_linker(msgid, self_back)
    lines.extend(card_view._link_line(r, ln, cl) for r in page_items)
    nav = nav_row(f"hgl:{gid}:{btok}", page, total_pages)
    kb = [nav] if nav else []
    kb.append([_btn(t("hub_btn_back"), back)])
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=kb)


async def _favorites_view(msgid: int | None = None) -> tuple[str, InlineKeyboardMarkup]:
    from bot import favorites_store
    from bot.entitykind import is_bot_username
    from bot.favorites import render_favorites
    from db.blacklist import is_favorite_blacklisted

    def vis(kind: str) -> list:
        return [r for r in favorites_store.load(kind) if not is_favorite_blacklisted(r)]

    def by_name(r):
        return (r["username"] is None, (r["username"] or r["title"] or "").lower())

    groups = sorted(vis("group"), key=lambda r: (r["title"] or r["username"] or "").lower())
    channels = sorted(vis("channel"), key=lambda r: (r["title"] or r["username"] or "").lower())
    # Load both 'user' and 'bot' favorites, then split by the username rule - so bots favorited before
    # this feature (saved as kind 'user') still land in the Bots section.
    people = vis("user") + vis("bot")
    users = sorted([r for r in people if not is_bot_username(r["username"])], key=by_name)
    bots = sorted([r for r in people if is_bot_username(r["username"])], key=by_name)
    if not groups and not channels and not users and not bots:
        return t("favorites_empty"), _back("home:home")
    # Each favorite opens its card in place (Back -> favorites), like every other hub list.
    return render_favorites(groups, channels, users, bots, _linker(msgid, "home:favs")), _back("home:home")


@router.callback_query(F.data.startswith("home:"))
async def on_home(callback: CallbackQuery, state: FSMContext) -> None:
    parts = callback.data.split(":")
    section = parts[1]
    await safe_answer(callback)
    # Navigating anywhere (except opening a prompt) cancels a pending text prompt, so a typed message
    # afterwards opens a card as usual instead of being swallowed as a search.
    if section not in ("su", "sb", "sg", "sc", "sl", "scm", "scms", "scl"):
        await state.clear()
    m = callback.message
    if section == "home":
        await safe_edit_text(m, *hub_home())
        note_hub_message(m.chat.id, m.message_id)  # keep this as the editable hub message
    elif section == "browse":
        await safe_edit_text(m, *_browse_menu())
    elif section == "usr":
        await safe_edit_text(m, *await _browse_people_view(int(parts[2]), m.message_id))
    elif section == "bot":
        await safe_edit_text(m, *await _browse_people_view(int(parts[2]), m.message_id, bots=True))
    elif section == "lnk":
        await safe_edit_text(m, *await _browse_links_view(int(parts[2]), m.message_id))
    elif section == "grp":
        await safe_edit_text(m, *await _list_view("group", int(parts[2]), m.message_id, "home:grp", "home:browse"))
    elif section == "chn":
        await safe_edit_text(m, *await _list_view("channel", int(parts[2]), m.message_id, "home:chn", "home:browse"))
    elif section == "stg":
        await safe_edit_text(m, *await _list_view("group", int(parts[2]), m.message_id, "home:stg", "home:stats"))
    elif section == "stc":
        await safe_edit_text(m, *await _list_view("channel", int(parts[2]), m.message_id, "home:stc", "home:stats"))
    elif section == "stm":
        await safe_edit_text(m, *await _stats_members_view(parts[2], int(parts[3]), m.message_id))
    elif section == "stl":
        await safe_edit_text(m, *await _stats_links_view(int(parts[2]), m.message_id))
    elif section == "data":
        await safe_edit_text(m, *_data_menu())
    elif section == "stats":
        await safe_edit_text(m, *await _stats_view(m.message_id))
    elif section == "expall":
        from bot.modules.admin import _export_full_zip
        await _export_full_zip(m)  # sends a zip document (a file can't go in an edited message)
    elif section == "delall":
        await safe_edit_text(m, *_delete_all_confirm())
    elif section == "check":
        await safe_edit_text(m, *_check_menu())
    elif section == "help":
        await safe_edit_text(m, *_help_view())
    elif section == "helpit":
        await safe_edit_text(m, *_help_view(it=True))
    elif section == "checkall":
        from bot import check_view
        view = await check_view.check_options(get_pool())
        await safe_edit_text(m, *(view or (t("check_nothing"), _back("home:check"))))
    elif section == "checklinks":
        from bot import check_view
        view = await check_view.check_options(get_pool(), links=True)
        await safe_edit_text(m, *(view or (t("check_links_nothing"), _back("home:check"))))
    elif section == "favs":
        await safe_edit_text(m, *await _favorites_view(m.message_id))
    elif section == "search":
        await safe_edit_text(m, *_search_menu())
    elif section == "su":
        await _prompt(m, state, "users", t("hub_prompt_su"), "home:search")
    elif section == "sb":
        await _prompt(m, state, "bots", t("hub_prompt_sb"), "home:search")
    elif section == "sg":
        await _prompt(m, state, "groups", t("hub_prompt_sg"), "home:search")
    elif section == "sc":
        await _prompt(m, state, "channels", t("hub_prompt_sc"), "home:search")
    elif section == "sl":
        await _prompt(m, state, "links", t("hub_prompt_sl"), "home:search")
    elif section == "scrape":
        await safe_edit_text(m, *_scrape_menu())
    elif section == "scm":
        await _prompt(m, state, "sc_members", t("hub_prompt_scm"), "home:scrape")
    elif section == "scms":
        await _prompt(m, state, "sc_messages", t("hub_prompt_scms"), "home:scrape")
    elif section == "scl":
        await _prompt(m, state, "sc_links", t("hub_prompt_scl"), "home:scrape")


@router.message(Command("start"))
async def cmd_start(message: Message, command: CommandObject) -> None:
    payload = (command.args or "").strip()
    # In-place clickable-text deep links ("g<token>"): edit the ORIGINATING message (its id rides in
    # the token) into a members/links/card view, then hide the "/start" the tap posted. This is the
    # only the /start payload is handled here.
    if payload.startswith("g") and len(payload) > 1:
        raw = get_token(payload[1:])
        try:
            data = json.loads(raw) if raw else None
        except (json.JSONDecodeError, TypeError):
            data = None
        if data:
            text, keyboard = await _inplace_view(data.get("a"), data)
            try:
                await message.bot.edit_message_text(text, chat_id=message.chat.id, message_id=data["msgid"], reply_markup=keyboard)
            except TelegramBadRequest:
                await message.answer(text, reply_markup=keyboard)
        else:
            # The token expired (LRU-evicted or the bot restarted), so we've lost the id of the message
            # the link was tapped from. Edit the tracked hub message in place (the list was almost
            # certainly shown there) instead of posting a floating message; fall back to a new one only
            # if there's no hub message to edit.
            hub_id = hub_message_id(message.chat.id)
            edited = False
            if hub_id is not None:
                try:
                    await message.bot.edit_message_text(t("card_expired"), chat_id=message.chat.id,
                                                        message_id=hub_id, reply_markup=_back("home:home"))
                    edited = True
                except TelegramBadRequest:
                    pass
            if not edited:
                await message.answer(t("card_expired"), reply_markup=_back("home:home"))
        try:
            await message.delete()
        except TelegramBadRequest:
            pass
        return

    log(f"📩 /start from tg_user_id={message.from_user.id} username={message.from_user.username}")
    text, keyboard = hub_home()
    sent = await message.answer(text, reply_markup=keyboard)
    note_hub_message(message.chat.id, sent.message_id)  # so a pasted link can edit THIS message
