"""Classify a resolved Telegram entity (person / group / channel), shared by the bot and the CLI
scrapers. Re-exported from bot/entitykind.py for the bot-side importers."""

USER = "user"
BOT = "bot"
GROUP = "group"
CHANNEL = "channel"


def is_bot_username(username: str | None) -> bool:
    """Telegram REQUIRES every bot's @username to end in 'bot' (and a bot always has a public username),
    so a username ending in 'bot' identifies a bot LOCALLY, with no API call. Reliable one way: if it
    doesn't end in 'bot' it isn't a bot. The reverse has at most rare edge cases (a person like @talbot),
    which Telegram largely reserves against anyway - accepted for the sake of a zero-cost classifier."""
    return bool(username) and username.strip().lstrip("@").lower().endswith("bot")


def _looks_like_bot(entity) -> bool:
    # A live entity's .bot flag is authoritative; otherwise the username rule, so the same answer holds
    # for a DB row (username only) and a resolved entity - one consistent classifier everywhere.
    return bool(getattr(entity, "bot", False)) or is_bot_username(entity_username(entity))


def classify_entity(entity) -> str | None:
    """'user', 'bot', 'group', 'channel', or None when it can't be told. A bot is a User whose username
    ends in 'bot'. A supergroup/megagroup or a legacy chat counts as a group; a broadcast channel as a
    channel."""
    try:
        from telethon.tl.types import Channel, ChannelForbidden, Chat, ChatForbidden, User
        if isinstance(entity, User):
            return BOT if _looks_like_bot(entity) else USER
        if isinstance(entity, (Channel, ChannelForbidden)):
            return GROUP if getattr(entity, "megagroup", False) else CHANNEL
        if isinstance(entity, (Chat, ChatForbidden)):
            return GROUP
    except ImportError:
        pass

    # Fallback: a title means group/channel (broadcast flag tells them apart), an id alone means a user
    # (or a bot, by the username rule).
    if getattr(entity, "title", None) is not None:
        if getattr(entity, "megagroup", False):
            return GROUP
        if getattr(entity, "broadcast", False):
            return CHANNEL
        return GROUP
    if getattr(entity, "id", None) is not None:
        return BOT if _looks_like_bot(entity) else USER
    return None


def entity_kind_label(entity) -> str:
    """A granular human label for the post-scrape confirmation: 'user', 'bot', 'supergroup', 'channel',
    'group', or 'chat'. Finer than classify_entity (which buckets supergroups into 'group')."""
    if getattr(entity, "title", None) is None:
        if getattr(entity, "id", None) is None:
            return "chat"
        return BOT if _looks_like_bot(entity) else USER
    if getattr(entity, "megagroup", False):
        return "supergroup"
    if getattr(entity, "broadcast", False) or getattr(entity, "gigagroup", False):
        return CHANNEL
    return GROUP


def entity_username(entity) -> str | None:
    """The entity's active public @username. Checks the classic scalar `.username` first, then the
    newer collectible-usernames list (`.usernames`): Telegram accounts/channels using multiple or
    Fragment usernames leave `.username` empty and expose the active handle only in `.usernames`,
    which is why such a user showed up in favorites as a plain name instead of a clickable @handle."""
    username = getattr(entity, "username", None)
    if username:
        return username
    for u in getattr(entity, "usernames", None) or []:
        if getattr(u, "active", False):
            return getattr(u, "username", None)
    return None


def entity_display(entity) -> str | None:
    """A label for an entity: a group/channel title, or a person's @handle / name / id."""
    title = getattr(entity, "title", None)
    if title:
        return title
    username = entity_username(entity)
    if username:
        return f"@{username}"
    parts = [getattr(entity, "first_name", None), getattr(entity, "last_name", None)]
    name = " ".join(p for p in parts if p)
    if name:
        return name
    uid = getattr(entity, "id", None)
    return str(uid) if uid is not None else None
