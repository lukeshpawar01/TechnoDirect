"""One data import at a time, across processes (SQLite allows a single writer).

The scheduled refresh (10:00 / 18:00) and the Supabase live sync (every 30 min, or by hand) share one lock file, taken
atomically, so a second run started meanwhile skips instead of fighting over the database ("database is locked").
"""
import os
import time
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings

MAX_AGE = 3 * 3600  # a lock older than this is from a crashed run


def lock_path():
    return Path(settings.BASE_DIR) / "data" / "scheduled_refresh.lock"


@contextmanager
def import_lock():
    """Yields True when this process holds the lock, False when another import is running."""
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and time.time() - path.stat().st_mtime >= MAX_AGE:
        path.unlink(missing_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        yield False
        return
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield True
    finally:
        path.unlink(missing_ok=True)
