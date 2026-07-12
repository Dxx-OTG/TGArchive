"""Counts and logs every outgoing Telegram RPC the shared client makes, so the terminal shows exactly
how many API calls each action costs and the running total for the session.

The counting client (collectors/telethon_client.py) routes every request through note_call(): since
all high-level calls (get_entity, iter_messages, iter_participants, CheckChatInvite, …) end up as one
or more raw requests through TelegramClient.__call__, counting there catches every real outgoing call
once. By default each line is printed (visible on the terminal); the bot points the sink at its logger
so the lines also land in the log file with a timestamp.
"""
_total = 0
_sink = print  # where each per-call line goes; the bot swaps this for bot.log.log (console + file)

# GetDifferenceRequest is Telethon's own background update-sync "heartbeat" (telethon/_updates/
# messagebox.py): it fires on its own, on a live connection, whenever the update sequence has a gap -
# completely independent of anything a command/card/check does, and unrelated to the resolve calls
# that actually risk a FloodWait. Excluded so the counter reflects only calls OUR actions trigger.
_EXCLUDED = {"GetDifferenceRequest"}


def set_sink(fn) -> None:
    """Route the per-call lines somewhere other than print (the bot points this at its log())."""
    global _sink
    _sink = fn


def note_call(request) -> None:
    """Record and announce one (or, for a batched request list, each) outgoing Telegram RPC, except the
    excluded background ones (see _EXCLUDED)."""
    global _total
    requests = request if isinstance(request, (list, tuple)) else [request]
    for r in requests:
        if type(r).__name__ in _EXCLUDED:
            continue
        _total += 1
        try:
            _sink(f"[Telegram API #{_total}] {type(r).__name__}")
        except Exception:
            pass


def total() -> int:
    """How many outgoing Telegram RPCs this process has made so far."""
    return _total


def reset() -> None:
    global _total
    _total = 0
