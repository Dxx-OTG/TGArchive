"""Shared FSM state for the /start hub's text prompts (Search / Scrape).

Set by the hub (bot/modules/start.py) when a prompt is opened; the text the user then types is caught
by the input handler in bot/modules/card.py (which owns the non-command text catch-all) and routed to
search or the entity card. One state with a `mode` in its data keeps the card's catch-all simple: it
just needs to yield while any hub prompt is active."""
from aiogram.fsm.state import State, StatesGroup


class HubInput(StatesGroup):
    waiting = State()
