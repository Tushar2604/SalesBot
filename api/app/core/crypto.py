"""Envelope encryption for stored secrets.

Everything sensitive that must be *used* later — LinkedIn session cookies, proxy
credentials, mailbox passwords, OAuth refresh tokens — is stored as ciphertext
and only ever decrypted inside a worker process.

Hard rules enforced by review:
  * plaintext never enters a log line, an API response, or an exception message;
  * decryption happens as late as possible and the plaintext is not retained;
  * in production a missing/short key is a startup failure, not a warning.
"""

from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


class SecretCryptoError(Exception):
    """Raised when a secret cannot be encrypted or decrypted."""


def _fernet() -> Fernet:
    key = settings.encryption_key.get_secret_value()
    if not key or key.startswith("CHANGE_ME"):
        if settings.is_production:
            raise SecretCryptoError("ENCRYPTION_KEY is not configured")
        # Dev/test convenience so the stack boots without a configured key.
        # Anything encrypted under a throwaway key is worthless, which is the point.
        key = key or Fernet.generate_key().decode()
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as exc:
        raise SecretCryptoError("ENCRYPTION_KEY is not a valid Fernet key") from exc


def encrypt_str(plaintext: str) -> bytes:
    return _fernet().encrypt(plaintext.encode())


def decrypt_str(ciphertext: bytes) -> str:
    try:
        return _fernet().decrypt(ciphertext).decode()
    except InvalidToken as exc:
        raise SecretCryptoError(
            "secret could not be decrypted (wrong key or corrupt data)"
        ) from exc


def encrypt_json(payload: dict[str, Any]) -> bytes:
    return encrypt_str(json.dumps(payload, separators=(",", ":")))


def decrypt_json(ciphertext: bytes) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(decrypt_str(ciphertext))
    return data
