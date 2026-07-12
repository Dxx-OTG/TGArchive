"""People/groups/channels to hide EVERYWHERE — as if they didn't exist. Blacklisted entries vanish
from every list, search, count (Stats and the per-group counts), link and favorites, in both the bot
and the CLI. Add entries below, then restart the bot/CLI (read once at startup)."""

# Telegram usernames (without @, case-insensitive) to exclude.
USERNAMES_BLACKLIST = {
    # "example_username",
}

# Telegram user IDs (numeric) to exclude.
USER_IDS_BLACKLIST = {
    # 123456789,
}

# Groups/channels to exclude: title, username (without @) or link (e.g. "t.me/name") all work.
GROUPS_BLACKLIST = {
    # "group_or_channel_name",
}
