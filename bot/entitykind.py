"""Re-export of the shared entity classifier (collectors/entitykind.py) for the bot side, so the bot
and the CLI scrapers use one implementation."""
from collectors.entitykind import (
    BOT,
    CHANNEL,
    GROUP,
    USER,
    classify_entity,
    entity_display,
    entity_kind_label,
    entity_username,
    is_bot_username,
)

__all__ = [
    "BOT", "CHANNEL", "GROUP", "USER",
    "classify_entity", "entity_display", "entity_kind_label", "entity_username", "is_bot_username",
]
