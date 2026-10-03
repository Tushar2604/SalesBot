"""API keys: generation, lookup and per-key rate limiting.

A key looks like `sr_live_<43 url-safe chars>`. Only its SHA-256 is stored;
the full key is shown once when created. A lookup hashes what was sent and
matches the hash, so a database leak does not leak working keys.
"""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid

import redis.asyncio as aioredis

from app.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

PREFIX = "sr_live_"


def generate() -> tuple[str, str, str]:
    """(full key, display prefix, hash)."""
    key = PREFIX + secrets.token_urlsafe(32)
    return key, key[: len(PREFIX) + 6], hash_key(key)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def looks_like_key(token: str) -> bool:
    return token.startswith(PREFIX)


_redis: aioredis.Redis | None = None


def _client() -> aioredis.Redis:
    global _redis
    if _redis is None:
        pool = aioredis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)
        _redis = aioredis.Redis(connection_pool=pool)
    return _redis


async def over_rate_limit(key_id: uuid.UUID) -> bool:
    """True when this key has used up this minute's requests. Fails open on a
    Redis problem: an outage must not take every integration down with it."""
    window = int(time.time() // 60)
    bucket = f"apikey:{key_id}:{window}"
    try:
        client = _client()
        count = int(await client.incr(bucket))
        if count == 1:
            await client.expire(bucket, 90)
    except Exception:  # see docstring
        log.warning("api_keys.rate_limit_unavailable", exc_info=True)
        return False
    return bool(count > settings.api_key_rate_limit_per_minute)
