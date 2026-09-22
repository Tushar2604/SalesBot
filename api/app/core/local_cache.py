"""Process-local fallback for Redis keys when the broker is unreachable.

Used for one-shot WebSocket tickets and per-account slot locks so a local
dev stack (Windows, no Docker Redis) can still open a remote-browser session.
Keys expire; this is not a substitute for Redis in production.
"""

from __future__ import annotations

import time
from threading import Lock

_lock = Lock()
_store: dict[str, tuple[str, float]] = {}


def _purge_locked(now: float) -> None:
    expired = [key for key, (_value, exp) in _store.items() if exp <= now]
    for key in expired:
        del _store[key]


def set_nx(key: str, value: str, ttl_seconds: int) -> bool:
    now = time.monotonic()
    with _lock:
        _purge_locked(now)
        existing = _store.get(key)
        if existing is not None and existing[1] > now:
            return False
        _store[key] = (value, now + max(ttl_seconds, 1))
        return True


def get(key: str) -> str | None:
    now = time.monotonic()
    with _lock:
        _purge_locked(now)
        item = _store.get(key)
        return item[0] if item else None


def expire(key: str, ttl_seconds: int) -> None:
    now = time.monotonic()
    with _lock:
        item = _store.get(key)
        if item is None:
            return
        _store[key] = (item[0], now + max(ttl_seconds, 1))


def delete_if_value(key: str, value: str) -> None:
    with _lock:
        item = _store.get(key)
        if item is not None and item[0] == value:
            del _store[key]
