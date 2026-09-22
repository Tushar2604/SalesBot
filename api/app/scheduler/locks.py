"""The single-execution-slot lock.

**One LinkedIn account performs one action at a time, forever.** Two concurrent
requests for one account — especially from two IPs — is the strongest signal
LinkedIn has that an account is automated. This lock is where that invariant is
enforced; worker concurrency settings are not a substitute, because they scale
with the pool rather than with the account.

TTL-guarded: a worker that is OOM-killed mid-action must not deadlock the
account forever. The TTL is deliberately longer than the HTTP timeout so the
lock cannot expire while a request is still in flight.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import redis

from app.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

# Longer than the driver's 30s HTTP timeout plus retries, short enough that a
# crashed worker frees the account within one dispatch cycle.
SLOT_TTL_SECONDS = 180

_pool: redis.ConnectionPool | None = None


def _client() -> redis.Redis:
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)
    return redis.Redis(connection_pool=_pool)


def slot_key(account_id: uuid.UUID | str) -> str:
    return f"li:acct:{account_id}:slot"


class SlotBusy(Exception):
    """The account is already performing an action."""


@contextmanager
def account_slot(account_id: uuid.UUID | str, *, ttl: int = SLOT_TTL_SECONDS) -> Iterator[None]:
    """Holds the account's only execution slot for the duration of the block.

    Raises `SlotBusy` rather than waiting: the dispatcher should move on to
    another account instead of blocking a worker on a queue.
    """
    key = slot_key(account_id)
    token = str(uuid.uuid4())
    client = _client()

    if not client.set(key, token, nx=True, ex=ttl):
        raise SlotBusy(f"account {account_id} is already acting")

    try:
        yield
    finally:
        # Release only if we still own it: if the TTL expired and another worker
        # took the slot, deleting it would let two actions run at once — the
        # exact thing this lock exists to prevent.
        try:
            if client.get(key) == token:
                client.delete(key)
        except redis.RedisError as exc:  # pragma: no cover - defensive
            log.warning("scheduler.slot_release_failed", account_id=str(account_id), error=str(exc))


def is_held(account_id: uuid.UUID | str) -> bool:
    return bool(_client().exists(slot_key(account_id)))
