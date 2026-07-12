"""Stats header helper for the /start hub's Stats drill-down (bot/modules/start.py). The hub renders
the totals and the member/link lists in place; this module provides the header builder. No router —
this module registers no handlers.
"""
from bot.i18n import plural, t


def _members_header(which: str, n: int) -> str:
    # Literal t("...") per branch so the i18n dead-key scanner sees each key used.
    if which == "bots":
        return t("stats_all_bots_header", n=n, word=plural(n, "Bot", "Bots"))
    word = plural(n, "User", "Users")
    if which == "with":
        return t("stats_with_username_header", n=n, word=word)
    if which == "without":
        return t("stats_without_username_header", n=n, word=word)
    return t("stats_all_members_header", n=n, word=word)
