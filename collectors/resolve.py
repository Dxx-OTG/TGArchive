"""Resolve a scrape target from user input, including PRIVATE invite links.

`client.get_entity()` handles public @usernames and t.me/<username> links, but NOT private invite
links (t.me/+HASH or t.me/joinchat/HASH): those carry an opaque invite hash, not a resolvable
username, so get_entity raises. For those we call CheckChatInvite, which returns the chat when the
scraping account has already joined it (the only case we can actually scrape). Shared by the bot's
scrape commands and the CLI scrapers so both accept the same inputs.
"""
import re

from telethon.tl.functions.messages import CheckChatInviteRequest

# t.me/+HASH  or  t.me/joinchat/HASH  (with or without the https:// and the t.me host).
_INVITE_RE = re.compile(r"(?:t\.me|telegram\.me)/(?:joinchat/|\+)([A-Za-z0-9_-]+)", re.IGNORECASE)


class NotAMemberError(RuntimeError):
    """The target is a private group/channel and the scraping account hasn't joined it, so its
    members/messages can't be read."""


def is_dead_reference(exc: Exception) -> bool:
    """True when a resolve failed because the reference is genuinely gone - a freed/invalid @username or
    a revoked/expired invite - so it's safe to remember as 'not found'. Transient failures (FloodWait,
    network, RPC) return False and are never cached, so they can recover on the next try."""
    from telethon import errors
    if isinstance(exc, (errors.UsernameNotOccupiedError, errors.UsernameInvalidError,
                        errors.InviteHashExpiredError, errors.InviteHashInvalidError)):
        return True
    return isinstance(exc, ValueError)  # get_entity raises ValueError ("Cannot find any entity …") for a freed handle


def invite_hash(text: str) -> str | None:
    """The invite hash from a private link, or None when the input isn't a private invite (a public
    @username or t.me/<username> link returns None and goes through get_entity as before)."""
    text = (text or "").strip()
    match = _INVITE_RE.search(text)
    if match:
        return match.group(1)
    if text.startswith("+"):
        return text[1:]
    if text.lower().startswith("joinchat/"):
        return text[len("joinchat/"):]
    return None


async def resolve_entity(client, group_input: str):
    """Resolve group_input to a Telegram entity. Accepts an @username, a t.me/<username> link, a
    numeric id, OR a private invite link (t.me/+HASH, t.me/joinchat/HASH) when the account already
    joined it. Raises NotAMemberError for a private link the account hasn't joined."""
    hash_ = invite_hash(group_input)
    if hash_ is None:
        return await client.get_entity(group_input)

    invite = await client(CheckChatInviteRequest(hash_))
    # Already a member -> ChatInviteAlready(chat=...); some layers return ChatInvitePeer(peer=...).
    chat = getattr(invite, "chat", None)
    if chat is not None:
        return chat
    peer = getattr(invite, "peer", None)
    if peer is not None:
        return await client.get_entity(peer)
    # ChatInvite (preview only) -> not joined; can't list members/messages without joining first.
    raise NotAMemberError(
        "that private invite points to a group/channel this account hasn't joined - open the link "
        "in Telegram and join it first, then scrape."
    )


async def invite_preview(client, hash_: str):
    """Look up a PRIVATE invite hash for DISPLAY/CHECK (not scraping): the real chat if this account
    already joined it, otherwise the ChatInvite PREVIEW (title + flags) of a valid invite it hasn't
    joined - so a card can open for a group we can't yet scrape. Raises InviteHashExpired/Invalid for a
    dead invite and FloodWaitError upward. Unlike resolve_entity, a valid-but-unjoined invite is NOT an
    error here - the card still shows, and only Scrape needs the account to be a member."""
    invite = await client(CheckChatInviteRequest(hash_))
    chat = getattr(invite, "chat", None)
    if chat is not None:
        return chat
    peer = getattr(invite, "peer", None)
    if peer is not None:
        return await client.get_entity(peer)
    return invite  # ChatInvite preview: valid invite, account just isn't a member
