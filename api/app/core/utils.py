"""Small shared helpers."""

from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(value: str, *, max_length: int = 60) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = _SLUG_STRIP.sub("-", normalized.lower()).strip("-")
    return slug[:max_length].strip("-") or "workspace"


def unique_slug(value: str, *, taken: set[str]) -> str:
    """Appends a short random suffix until the slug is free."""
    base = slugify(value)
    if base not in taken:
        return base
    for _ in range(10):
        candidate = f"{base[:52]}-{secrets.token_hex(3)}"
        if candidate not in taken:
            return candidate
    return f"{base[:46]}-{secrets.token_hex(8)}"


def generate_token(nbytes: int = 32) -> str:
    """URL-safe opaque token for invite links, API keys, unsubscribe links."""
    return secrets.token_urlsafe(nbytes)


def hash_token(token: str) -> str:
    """SHA-256 hex digest. Used for tokens we must look up but never reveal again.

    Unlike passwords these are high-entropy random values, so a fast hash is the
    right choice — there is nothing to brute-force.
    """
    return hashlib.sha256(token.encode()).hexdigest()
