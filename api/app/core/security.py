"""Password hashing and JWT issuance/verification."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.config import settings

# Argon2id with sensible interactive parameters.
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    return True


def needs_rehash(password_hash: str) -> bool:
    """True when Argon2 parameters changed and the hash should be upgraded on next login."""
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def _encode(
    subject: str,
    token_type: TokenType,
    ttl: timedelta,
    extra: dict[str, Any] | None = None,
) -> tuple[str, str, datetime]:
    """Returns (encoded_jwt, jti, expires_at)."""
    now = datetime.now(UTC)
    expires_at = now + ttl
    jti = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "sub": subject,
        "typ": token_type,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    if extra:
        payload.update(extra)
    encoded = jwt.encode(
        payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm
    )
    return encoded, jti, expires_at


def create_access_token(user_id: uuid.UUID, workspace_id: uuid.UUID | None = None) -> str:
    extra = {"ws": str(workspace_id)} if workspace_id else None
    token, _, _ = _encode(
        str(user_id),
        "access",
        timedelta(minutes=settings.access_token_ttl_minutes),
        extra,
    )
    return token


def create_refresh_token(user_id: uuid.UUID) -> tuple[str, str, datetime]:
    """Refresh tokens are rotated; the jti is persisted so it can be revoked."""
    return _encode(str(user_id), "refresh", timedelta(days=settings.refresh_token_ttl_days))


class TokenError(Exception):
    """Raised when a token is missing, malformed, expired, or of the wrong type."""


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "typ", "jti"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("invalid token") from exc

    if payload.get("typ") != expected_type:
        raise TokenError(f"expected {expected_type} token")
    return payload


# ── remote-browser WS tickets ────────────────────────────────────────────────
# Kept separate from `TokenType`/`decode_token` rather than widening that
# Literal: an access/refresh token authenticates a person across many requests,
# a WS ticket authenticates exactly one browser-controlled WebSocket connect
# and is spent the instant it's used (see routes_linkedin_remote.py). Mixing
# the two into one type would make it easy to accidentally accept one where
# the other is expected.

_WS_TICKET_TYPE = "remote_browser"


def encode_ws_ticket(
    user_id: uuid.UUID, workspace_id: uuid.UUID, account_id: uuid.UUID, ttl: timedelta
) -> tuple[str, str, datetime]:
    """Returns (encoded_jwt, jti, expires_at). The jti is the one-time-use key."""
    now = datetime.now(UTC)
    expires_at = now + ttl
    jti = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "typ": _WS_TICKET_TYPE,
        "jti": jti,
        "ws": str(workspace_id),
        "acct": str(account_id),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    encoded = jwt.encode(
        payload, settings.jwt_secret.get_secret_value(), algorithm=settings.jwt_algorithm
    )
    return encoded, jti, expires_at


def decode_ws_ticket(token: str) -> dict[str, Any]:
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "typ", "jti", "ws", "acct"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("ticket expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("invalid ticket") from exc

    if payload.get("typ") != _WS_TICKET_TYPE:
        raise TokenError("expected a remote-browser ticket")
    return payload
