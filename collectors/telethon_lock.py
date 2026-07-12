import os
from pathlib import Path

try:
    import msvcrt
except ImportError:
    msvcrt = None  # Windows-only module; fail soft elsewhere instead of crashing on import.

LOCK_PATH = Path("telethon_session.lock")

_lock_fd: int | None = None


class TelethonSessionBusy(RuntimeError):
    """Raised when another TGArchive process already holds the exclusive Telethon connection lock."""


def acquire_telethon_lock() -> None:
    """Raises TelethonSessionBusy if another process already holds the lock. No-op if this process
    already holds it."""
    global _lock_fd
    if _lock_fd is not None:
        return

    if msvcrt is None:
        return

    fd = os.open(str(LOCK_PATH), os.O_RDWR | os.O_CREAT)
    try:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    except OSError as e:
        os.close(fd)
        raise TelethonSessionBusy(
            "another TGArchive process (the bot or the CLI) is already connected to "
            "Telegram with this account - close it first, then try again"
        ) from e

    _lock_fd = fd


def release_telethon_lock() -> None:
    global _lock_fd
    if _lock_fd is None:
        return
    if msvcrt is not None:
        try:
            msvcrt.locking(_lock_fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        os.close(_lock_fd)
    _lock_fd = None
