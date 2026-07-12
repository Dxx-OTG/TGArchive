"""Rendering for the entity card (handlers in bot/modules/card.py): the card itself and its in-place
drill-downs (members / links / a user's groups), each with a "back to card" button.

The drill-downs reuse the data layer (members_q / links_q) and the shared pagination, opening their
lists in place by editing the card message rather than posting a new one.
"""
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.entitykind import BOT, CHANNEL, GROUP, USER
from bot.group_links import dedupe_groups, group_link, link_display
from bot.inplace import linker as _linker, link_card_ref, sharers_linker as _sharers_linker
from bot.i18n import plural, t
from bot.pagination import btn as _btn, nav_row, page_line, paginate
from collectors import check
from db.queries import links as links_q
from db.queries import members as members_q

_ICON = {CHANNEL: "📢", GROUP: "📂", USER: "👤", BOT: "🤖"}
# A bot behaves like a user in the card: a leaf entity you can view (its groups/links), favorite and
# check - never scraped for its own contents.
_LEAF_KINDS = (USER, BOT)
_USER_CAP = 30
# Link rows carry up to 2 clickable links each (the name -> card, the 👤 N -> sharers) plus a group
# subheader, so cap link pages at 30 to stay under Telegram's ~100 formatting-entity limit.
_LINKS_PER_PAGE = 30
# How many recent messages to read, offered before a messages/links scrape (capped at 5000, the
# scrapers' MAX_LIMIT).
_LIMIT_PRESETS = [100, 500, 1000, 3000, 5000]


def _back_row(token: str) -> list[InlineKeyboardButton]:
    return [_btn(t("card_btn_back"), f"cd:crd:{token}")]


def _entity_name(target) -> str:
    title = escape(target.title or (f"@{target.username}" if target.username else str(target.tg_id)))
    return f'<a href="{escape(target.link)}">{title}</a>' if target.link else title


def _kind_word(kind: str) -> str:
    if kind == CHANNEL:
        return t("card_kind_channel")
    if kind == BOT:
        return t("card_kind_bot")
    if kind == USER:
        return t("card_kind_user")
    return t("card_kind_group")


# --- the card -----------------------------------------------------------------------------------

def render_card(target, state, token: str, back: str | None = None) -> tuple[str, InlineKeyboardMarkup]:
    lines = [f"{_ICON.get(target.kind, '•')} <b>{_entity_name(target)}</b>"]
    lines.append(f"{_kind_word(target.kind)} · " + (t("card_in_archive") if state.in_archive else t("card_not_archived")))
    if state.in_archive:
        if target.kind in _LEAF_KINDS:
            lines.append(t("card_user_line", groups=state.groups, links=state.links))
        else:
            lines.append(t("card_group_line", members=state.members, links=state.links))
    if state.check_status:
        lines.append(t("card_check_line", glyph=check.status_glyph(state.check_status), age=escape(check.age_text(state.check_entry))))
    if state.is_favorite:
        lines.append(t("card_fav_on"))

    rows: list[list[InlineKeyboardButton]] = []
    if target.kind in _LEAF_KINDS:
        if not state.in_archive:
            rows.append([_btn(t("card_btn_add"), f"cd:add:{token}")])  # register the standalone user/bot
        else:
            rows.append([_btn(t("card_btn_usergroups"), f"cd:usr:{token}:0")])
            if state.groups == 0:  # a standalone (registered) member, not a scraped one -> can un-register
                rows.append([_btn(t("card_btn_delete"), f"cd:del:{token}")])
    else:
        if not state.in_archive:
            rows.append([_btn(t("card_btn_add"), f"cd:add:{token}")])
        browse = []
        if target.kind == GROUP and state.members:
            browse.append(_btn(t("card_btn_members"), f"cd:mem:{token}:0"))
        if state.links:
            browse.append(_btn(t("card_btn_links"), f"cd:lnk:{token}:0"))
        if browse:
            rows.append(browse)
        scrape_label = t("card_btn_rescrape") if (state.members or state.links) else t("card_btn_scrape")
        rows.append([_btn(scrape_label, f"cd:scr:{token}")])
        if state.in_archive:
            rows.append([_btn(t("card_btn_export"), f"cd:exp:{token}"), _btn(t("card_btn_delete"), f"cd:del:{token}")])

    fav_label = t("card_btn_unfav") if state.is_favorite else t("card_btn_fav")
    rows.append([_btn(t("card_btn_check"), f"cd:chk:{token}"), _btn(fav_label, f"cd:fav:{token}")])
    if back:  # opened from a list/scrape -> a top-level Back to that origin
        rows.append([_btn(t("card_btn_back"), back)])

    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


# --- scrape sub-menus (in-place on the card message) --------------------------------------------

def scrape_menu(target, token: str) -> tuple[str, InlineKeyboardMarkup]:
    """The group scrape picker: members (no limit) / message senders / links. Channels skip this and
    go straight to the links limit picker (handled in bot/modules/card.py)."""
    rows = [[
        _btn(t("card_btn_scr_members"), f"cd:sc:{token}:m"),
        _btn(t("card_btn_scr_messages"), f"cd:sc:{token}:msg"),
        _btn(t("card_btn_scr_links"), f"cd:sc:{token}:lnk"),
    ], _back_row(token)]
    return t("card_scrape_menu"), InlineKeyboardMarkup(inline_keyboard=rows)


def delete_confirm(target, token: str) -> tuple[str, InlineKeyboardMarkup]:
    """Confirm removing this entity's CSVs from the archive (the watcher then prunes the DB)."""
    rows = [[
        _btn(t("card_btn_delete_yes"), f"cd:dely:{token}"),
        _btn(t("card_btn_back"), f"cd:crd:{token}"),
    ]]
    return t("card_delete_confirm", title=_entity_name(target)), InlineKeyboardMarkup(inline_keyboard=rows)


def limit_menu(target, token: str, which: str) -> tuple[str, InlineKeyboardMarkup]:
    """Pick how many recent messages to read, then run the messages/links scrape. Back goes to the
    group scrape menu, or straight to the card for a channel (which had no menu)."""
    presets = [_btn(str(n), f"cd:sc:{token}:{which}:{n}") for n in _LIMIT_PRESETS]
    back = f"cd:scr:{token}" if target.kind == GROUP else f"cd:crd:{token}"
    rows = [presets, [_btn(t("card_btn_back"), back)]]
    return t("card_limit_menu"), InlineKeyboardMarkup(inline_keyboard=rows)


# --- in-place drill-downs -----------------------------------------------------------------------

def _member_line(r, linker=None) -> str:
    if r["username"]:
        label = f'@{r["username"]}'
        name = linker(f'@{r["username"]}', label) if linker else escape(label)
        return f'• {name} — <code>{r["tg_user_id"]}</code>'
    return f'• {t("members_no_username")} — <code>{r["tg_user_id"]}</code>'


def _link_line(r, linker=None, count_linker=None) -> str:
    label = link_display(r["link"])
    name = linker(link_card_ref(r["link"]), label) if linker else escape(label)
    line = f'• {name}'
    # Instead of the single sender's @name, show 👤 N = how many people shared this link (by link_key),
    # clickable to that list. count_linker builds the in-place deep link; without it, plain text.
    n = r["sharers"] if "sharers" in r.keys() else 0
    if n:
        line += " — " + (count_linker(links_q.link_key(r["link"]), n) if count_linker else f"👤 {n}")
    return line


def link_lines_by_group(rows, linker=None, count_linker=None, *, group_as_card: bool = True) -> list[str]:
    """Lines for a link list grouped by the source channel/group: a subheader whenever the source
    changes (and at the top of a page), then that group's links. `rows` must be pre-sorted by
    (group_title, link) and carry the group_* columns. The subheader opens the group's card when
    `group_as_card` (default); pass False for plain bold text (e.g. inside a user card, where the
    groups are already listed above). Each link opens its card via `linker`; its 👤 N sharers count
    opens the sharers list via `count_linker`."""
    lines: list[str] = []
    prev = object()
    for r in rows:
        title = r["group_title"] or "?"
        if title != prev:
            prev = title
            icon = "📢" if r["group_kind"] == "channel" else "📂"
            if group_as_card and linker:
                handle = group_link(r["group_username"], r["group_invite"]) or r["group_invite"] or title
                name = linker(handle, title)
            else:
                name = escape(title)
            lines.append(f"{icon} <b>{name}</b>")
        lines.append(_link_line(r, linker, count_linker))
    return lines


async def render_members(pool, state, token: str, page: int, msgid: int | None = None):
    if state.group_id is None:
        return None
    rows = await members_q.list_distinct_group_members(pool, state.group_id)
    if not rows:
        return None
    page_items, page, total_pages = paginate(rows, page)
    lines = [t("card_members_header", n=len(rows), word=plural(len(rows), "Member", "Members"))]
    if pl := page_line(page, total_pages):
        lines.append(pl)
    lines.append("")
    linker = _linker(msgid, f"cd:mem:{token}:{page}")  # a member's card returns to this list page
    lines.extend(_member_line(r, linker) for r in page_items)
    keyboard = _nav_and_back(f"cd:mem:{token}", page, total_pages, token)
    return "\n".join(lines), keyboard


async def render_links(pool, state, token: str, page: int, msgid: int | None = None):
    if state.group_id is None:
        return None
    rows = await links_q.links_for_group(pool, state.group_id)
    if not rows:
        return None
    page_items, page, total_pages = paginate(rows, page, _LINKS_PER_PAGE)
    lines = [t("card_links_header", n=len(rows), word=plural(len(rows), "Link", "Links"))]
    if pl := page_line(page, total_pages):
        lines.append(pl)
    lines.append("")
    back = f"cd:lnk:{token}:{page}"  # a link's / sharers' view returns to this list page
    linker = _linker(msgid, back)
    count_linker = _sharers_linker(msgid, back)
    lines.extend(_link_line(r, linker, count_linker) for r in page_items)
    keyboard = _nav_and_back(f"cd:lnk:{token}", page, total_pages, token)
    return "\n".join(lines), keyboard


async def render_user(pool, target, token: str, back_cb: str | None = None, msgid: int | None = None,
                      inner_back: str | None = None):
    uid = target.tg_id
    if uid is None and target.username:
        mem = await members_q.find_member(pool, username=target.username)
        uid = mem["tg_user_id"] if mem else None
    if uid is None:
        return None

    group_rows = await members_q.find_member_groups(pool, str(uid))
    link_rows = await links_q.links_by_user(pool, uid)
    if not group_rows and not link_rows:
        return None
    groups = dedupe_groups(group_rows, link_fn=lambda r: group_link(r["group_username"], r["invite_input"]))

    # A group/link tapped inside this detail opens its card and returns HERE (to this detail): the
    # caller passes inner_back to re-enter it - `cd:usr:…` for a card drill, `iv:…` for the hub (a
    # deep-link view). Falls back to the card-drill re-entry.
    inner = inner_back or (back_cb if back_cb else f"cd:usr:{token}:0")
    linker = _linker(msgid, inner)
    count_linker = _sharers_linker(msgid, inner)

    lines = [f"👤 {_entity_name(target)}"]
    if groups:
        lines.append(t("card_user_groups", n=len(groups), word=plural(len(groups), "Group", "Groups")))
        for r in groups[:_USER_CAP]:
            title = r["title"] or "?"
            handle = group_link(r["group_username"], r["invite_input"]) or r["invite_input"] or title
            lines.append(f"• {linker(handle, title)}" if linker else f"• {escape(title)}")
        if len(groups) > _USER_CAP:
            lines.append(t("list_more", n=len(groups) - _USER_CAP))
    if link_rows:
        lines.append(t("card_user_links", n=len(link_rows), word=plural(len(link_rows), "Link", "Links")))
        # Grouped by source group (plain subheaders - the groups are already clickable in the list above).
        lines.extend(link_lines_by_group(link_rows[:_USER_CAP], linker, count_linker, group_as_card=False))
        if len(link_rows) > _USER_CAP:
            lines.append(t("list_more", n=len(link_rows) - _USER_CAP))

    # From the card, Back returns to the card; opened in place from a hub list, Back returns to that list.
    back_row = [_btn(t("card_btn_back"), back_cb)] if back_cb else _back_row(token)
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=[back_row])


def _nav_and_back(prefix: str, page: int, total_pages: int, token: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    nav = nav_row(prefix, page, total_pages)
    if nav:
        rows.append(nav)
    rows.append(_back_row(token))
    return InlineKeyboardMarkup(inline_keyboard=rows)
