"""Each LinkedIn account's saved browser profile: one "computer", for life.

Launching a fresh browser for every action, carrying only the login cookies,
looks to LinkedIn like a brand-new device dozens of times a day. A persistent
profile keeps everything a real browser accumulates — cookies, local storage,
IndexedDB, cache, service workers — so the sign-in and every later action run
on the same machine, the way one person's laptop would.

Only one browser may open a profile at a time. The account's execution slot
(`scheduler.locks.account_slot`, and the remote-browser slot) already
guarantees that, so a leftover Chromium lock — from a crash, or from the other
container (sign-in runs in `api`, actions in `worker`) — is stale by
definition and is cleared before launch.
"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from app.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

# Chromium's "profile in use" markers. Hostname-bound, so a lock written by
# the api container would otherwise block the worker forever.
_LOCK_FILES = ("SingletonLock", "SingletonCookie", "SingletonSocket")


def path_for(account_id: uuid.UUID | str) -> Path:
    return Path(settings.browser_profiles_dir) / str(uuid.UUID(str(account_id)))


def prepare(account_id: uuid.UUID | str) -> str:
    """The account's profile directory, created if new and unlocked for launch.

    Callers must hold the account's execution slot.
    """
    directory = path_for(account_id)
    directory.mkdir(parents=True, exist_ok=True)
    for name in _LOCK_FILES:
        lock = directory / name
        if lock.is_symlink() or lock.exists():
            lock.unlink(missing_ok=True)
    return str(directory)


def wipe(account_id: uuid.UUID | str) -> None:
    """Deletes the saved profile, and the session inside it, for good.

    For disconnect, revoke and delete: a signed-out account must not keep a
    logged-in browser lying around.
    """
    directory = path_for(account_id)
    if directory.exists():
        shutil.rmtree(directory, ignore_errors=True)
        log.info("linkedin.browser_profile.wiped", account_id=str(account_id))
