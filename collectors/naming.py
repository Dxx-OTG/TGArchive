import re

# Characters Windows forbids in filenames (plus control chars); letters from any language are kept.
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_group_filename(title: str | None, fallback) -> str:
    """Filesystem-safe base name for a group's CSV: strips only Windows-illegal chars, and falls
    back to the group id when nothing usable is left (e.g. an emoji-only title)."""
    name = _ILLEGAL.sub("", title or "").strip().strip(".").strip()
    return name or str(fallback)
