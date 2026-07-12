"""Rendering for the hub's Check views (handlers in bot/modules/check.py): the summary, the per-kind
drill-down lists and the remove-inactive confirmation, all as Telegram HTML + inline keyboards.

Everything is derived live from collectors.check.build_view (stateless, like the rest of the bot),
so a button tapped later always reflects the current stored status. Entity names stay clickable even
when unreachable, per the design (a dead channel's name still links to its recorded t.me link)."""
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.entitykind import BOT, CHANNEL, GROUP, USER
from bot.i18n import plural, t
from bot.pagination import btn as _btn, nav_row, page_line, paginate
from collectors.check import (
    STATUS_OK,
    TargetStatus,
    age_text,
    build_link_view,
    build_view,
    gather_link_targets,
    gather_targets,
    is_dead,
    is_fresh,
    load_status,
    status_glyph,
)

# List cap for the confirmation preview (the lists themselves paginate).
_CONFIRM_PREVIEW = 30

_KIND_LETTER = {"g": GROUP, "c": CHANNEL, "u": USER, "b": BOT}


# Literal t("...") per branch so the i18n dead-key scanner sees each key used (like bot/modules/stats.py).
def _list_header(which: str, n: int) -> str:
    if which == "g":
        return t("check_list_groups_header", n=n)
    if which == "c":
        return t("check_list_channels_header", n=n)
    if which == "u":
        return t("check_list_users_header", n=n)
    if which == "b":
        return t("check_list_bots_header", n=n)
    return t("check_list_lastcheck_header", n=n)


def _name_html(target) -> str:
    title = escape(target.title or "?")
    if target.link:
        return f'<a href="{escape(target.link)}">{title}</a>'
    return title


def _entity_line(x: TargetStatus, *, show_age: bool = False) -> str:
    star = "⭐ " if x.target.is_favorite else ""
    line = f"• {status_glyph(x.status)} {star}{_name_html(x.target)}"
    if show_age:
        line += f" · <i>{escape(age_text(x.entry))}</i>"
    return line


def _counts(items: list[TargetStatus]) -> dict:
    ok = sum(1 for x in items if x.status == STATUS_OK)
    dead = sum(1 for x in items if is_dead(x.status))
    unchecked = sum(1 for x in items if x.status is None)  # never probed (▫️) - NOT a transient error
    # ⚠️ (unknown) is only the transient failures actually probed; ▫️ (unchecked) is counted apart so a
    # partial run doesn't look like hundreds of "couldn't verify".
    return {"ok": ok, "dead": dead, "unknown": len(items) - ok - dead - unchecked,
            "unchecked": unchecked, "total": len(items)}


# --- pre-check options ---------------------------------------------------------------------------

async def check_options(pool, *, links: bool = False):
    """The screen shown when Check All / Check Links is tapped, INSTEAD of running immediately: how
    many targets there are and how many already have a fresh (<24h) result, plus the choice to
    re-check everything (force), skip the recent ones, or just view the last summary. Returns None
    when there's nothing to check at all (the caller shows the 'nothing' message)."""
    targets = await (gather_link_targets(pool) if links else gather_targets(pool))
    if not targets:
        return None
    store = load_status()
    fresh = sum(1 for tt in targets if (e := store.get(tt.canonical_key)) and is_fresh(e))
    header = t("check_links_header") if links else t("check_summary_header")
    # First run (nothing checked in the last 24h) reads as a plain "Check"; only once some results
    # are still fresh does forcing them over count as a "Re-check" (and unlock "Skip recent").
    if fresh:
        body = t("check_options_body", total=len(targets), fresh=fresh)
        run_label = t("check_btn_full")
    else:
        body = t("check_options_body_none", total=len(targets))
        run_label = t("check_btn_run")

    k = "l" if links else "a"
    rows: list[list[InlineKeyboardButton]] = [[_btn(run_label, f"chkrun:{k}:f")]]
    if fresh:  # nothing to skip when none are fresh
        rows.append([_btn(t("check_btn_skip", n=fresh), f"chkrun:{k}:s")])
    rows.append([_btn(t("check_btn_summary"), f"chksum:{k}")])
    rows.append([_btn(t("hub_btn_back"), "home:check")])
    return f"{header}\n\n{body}", InlineKeyboardMarkup(inline_keyboard=rows)


# --- summary ------------------------------------------------------------------------------------

async def summary(pool, *, links: bool = False) -> tuple[str, InlineKeyboardMarkup | None]:
    """Reachability summary, shared by Check All and Check Links. links=True builds from the archived
    links (grouped by the kind each turned out to be) and uses the parallel `lchk` drill-down
    callbacks; otherwise it covers every scraped/favorite entity via the `chk` callbacks."""
    view = await (build_link_view(pool) if links else build_view(pool))
    groups = [x for x in view if x.target.kind == GROUP]
    channels = [x for x in view if x.target.kind == CHANNEL]
    users = [x for x in view if x.target.kind == USER]
    bots = [x for x in view if x.target.kind == BOT]
    checked = [x for x in view if x.entry is not None]

    lines = [
        t("check_links_header") if links else t("check_summary_header"),
        t("check_summary_groups", **_counts(groups)),
        t("check_summary_channels", **_counts(channels)),
        t("check_summary_users", **_counts(users)),
        t("check_summary_bots", **_counts(bots)),
        t("check_summary_lastcheck", n=len(checked)),
    ]

    prefix = "lchk" if links else "chk"
    rows: list[list[InlineKeyboardButton]] = []
    if groups:
        rows.append([_btn(t("check_btn_groups", n=len(groups)), f"{prefix}:g:0")])
    if channels:
        rows.append([_btn(t("check_btn_channels", n=len(channels)), f"{prefix}:c:0")])
    if users:
        rows.append([_btn(t("check_btn_users", n=len(users)), f"{prefix}:u:0")])
    if bots:
        rows.append([_btn(t("check_btn_bots", n=len(bots)), f"{prefix}:b:0")])
    if checked:
        rows.append([_btn(t("check_btn_lastcheck", n=len(checked)), f"{prefix}:l:0")])
    # Back goes one step up, to the pre-check options screen this summary was reached through (Full /
    # Skip / Last summary), not straight to the Check menu - so navigation unwinds step by step.
    rows.append([_btn(t("hub_btn_back"), "home:checklinks" if links else "home:checkall")])

    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


# --- drill-down lists ---------------------------------------------------------------------------

async def list_view(pool, which: str, page: int, *, links: bool = False, exclude: set[str] | None = None):
    """(text, keyboard) for one drill-down, or None when it's empty. which: g/c/u per kind, l for the
    'last checked' list. links=True drills into the Check Links view (parallel `lchk` callbacks).
    exclude drops just-removed keys so they vanish before the watcher has pruned the DB."""
    if links:
        view = await build_link_view(pool, exclude=exclude)
    else:
        view = await build_view(pool)
        if exclude:
            view = [x for x in view if x.target.canonical_key not in exclude]

    if which == "l":
        # "Last checked": everything that has a stored result, most recently checked first.
        items = sorted(
            [x for x in view if x.entry is not None],
            key=lambda x: (x.entry or {}).get("checked_at") or "",
            reverse=True,
        )
        header, show_age, can_remove = _list_header("l", len(items)), True, False
    else:
        kind = _KIND_LETTER[which]
        items = [x for x in view if x.target.kind == kind]
        header, show_age, can_remove = _list_header(which, len(items)), False, True

    if not items:
        return None

    prefix = "lchk" if links else "chk"
    rmprefix = "lchkrm" if links else "chkrm"
    page_items, page, total_pages = paginate(items, page)
    lines = [header]
    if pl := page_line(page, total_pages):
        lines.append(pl)
    lines.append("")
    lines.extend(_entity_line(x, show_age=show_age) for x in page_items)

    rows: list[list[InlineKeyboardButton]] = []
    dead = [x for x in items if is_dead(x.status)]
    if can_remove and dead:
        rows.append([_btn(t("check_remove_btn", n=len(dead)), f"{rmprefix}:{which}")])
    nav = nav_row(f"{prefix}:{which}", page, total_pages)
    if nav:
        rows.append(nav)
    rows.append([_btn(t("check_btn_back"), f"{prefix}:s:0")])

    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)


# --- remove-inactive confirmation ---------------------------------------------------------------

async def remove_confirm_view(pool, which: str, *, links: bool = False):
    """(text, keyboard) asking to confirm removal of the dead entities/links of this kind, or None if
    there are none. links=True targets the archived links (removed from the link CSVs)."""
    kind = _KIND_LETTER[which]
    view = await (build_link_view(pool) if links else build_view(pool))
    dead = [x for x in view if x.target.kind == kind and is_dead(x.status)]
    if not dead:
        return None

    if links:
        head = t("check_links_remove_confirm", n=len(dead), word=plural(len(dead), "link", "links"))
        yes_btn, yes_cb, cancel_cb = t("check_links_remove_yes_btn"), f"lchkrmy:{which}", f"lchk:{which}:0"
    else:
        head = t("check_remove_confirm", n=len(dead), word=plural(len(dead), "entity", "entities"))
        yes_btn, yes_cb, cancel_cb = t("check_remove_yes_btn"), f"chkrmy:{which}", f"chk:{which}:0"

    lines = [head, ""]
    lines.extend(f"• {status_glyph(x.status)} {_name_html(x.target)}" for x in dead[:_CONFIRM_PREVIEW])
    if len(dead) > _CONFIRM_PREVIEW:
        lines.append(t("list_more", n=len(dead) - _CONFIRM_PREVIEW))

    rows = [[_btn(yes_btn, yes_cb), _btn(t("check_remove_cancel_btn"), cancel_cb)]]
    return "\n".join(lines), InlineKeyboardMarkup(inline_keyboard=rows)
