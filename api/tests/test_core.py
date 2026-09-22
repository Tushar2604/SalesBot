"""Crypto, log redaction, and token handling.

These are the pieces whose failure modes are silent: a secret that round-trips
wrong is noticed immediately, but a secret that leaks into a log line is not.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.core.crypto import SecretCryptoError, decrypt_json, decrypt_str, encrypt_json, encrypt_str
from app.core.logging import redaction_processor
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.core.utils import hash_token, slugify, unique_slug


def test_password_hash_is_salted_and_verifies() -> None:
    first = hash_password("correct horse 7")
    second = hash_password("correct horse 7")

    assert first != second  # per-hash salt
    assert first.startswith("$argon2id$")
    assert verify_password("correct horse 7", first)
    assert not verify_password("correct horse 8", first)


def test_verify_password_rejects_garbage_hash_without_raising() -> None:
    assert not verify_password("anything", "not-a-hash")


def test_access_token_round_trips_with_workspace_claim() -> None:
    user_id, workspace_id = uuid.uuid4(), uuid.uuid4()
    payload = decode_token(create_access_token(user_id, workspace_id), "access")

    assert payload["sub"] == str(user_id)
    assert payload["ws"] == str(workspace_id)
    assert payload["typ"] == "access"


def test_refresh_token_cannot_be_used_as_an_access_token() -> None:
    token, jti, expires_at = create_refresh_token(uuid.uuid4())

    assert decode_token(token, "refresh")["jti"] == jti
    assert expires_at > expires_at - timedelta(seconds=1)

    # Type confusion would let a long-lived refresh token authenticate requests.
    with pytest.raises(TokenError):
        decode_token(token, "access")


def test_tampered_token_is_rejected() -> None:
    token = create_access_token(uuid.uuid4())
    with pytest.raises(TokenError):
        decode_token(token[:-2] + "xy", "access")


def test_secret_round_trip() -> None:
    session = {"li_at": "AQEDAT...", "JSESSIONID": "ajax:123", "user_agent": "LinkedIn/9.1"}

    ciphertext = encrypt_json(session)
    assert b"AQEDAT" not in ciphertext  # plaintext must not survive in the blob
    assert decrypt_json(ciphertext) == session

    assert decrypt_str(encrypt_str("li_at=secret")) == "li_at=secret"


def test_corrupt_ciphertext_raises_a_domain_error() -> None:
    with pytest.raises(SecretCryptoError):
        decrypt_str(b"not-a-fernet-token")


def test_redaction_masks_known_secret_keys() -> None:
    event = {
        "event": "linkedin.action",
        "password": "hunter2",
        "session_ciphertext": b"...",
        "nested": {"li_at": "AQEDAT", "safe": "keep me"},
        "list": [{"api_key": "sk-123"}],
    }

    cleaned = redaction_processor(None, "", event)  # type: ignore[arg-type]

    assert cleaned["password"] == "«redacted»"
    assert cleaned["session_ciphertext"] == "«redacted»"
    assert cleaned["nested"]["li_at"] == "«redacted»"
    assert cleaned["nested"]["safe"] == "keep me"
    assert cleaned["list"][0]["api_key"] == "«redacted»"
    assert cleaned["event"] == "linkedin.action"


def test_redaction_masks_secrets_embedded_in_free_text() -> None:
    # Upstream error bodies routinely echo the request's cookie header back.
    event = {
        "event": "upstream.error",
        "body": 'Set-Cookie: li_at=AQEDATxyz; JSESSIONID="ajax:99"',
        "headers": "Authorization: Bearer eyJhbGciOi.payload.sig",
    }

    cleaned = redaction_processor(None, "", event)  # type: ignore[arg-type]

    assert "AQEDATxyz" not in cleaned["body"]
    assert "li_at=«redacted»" in cleaned["body"]
    assert "ajax:99" not in cleaned["body"]
    assert "eyJhbGciOi" not in cleaned["headers"]


def test_slugify_and_unique_slug() -> None:
    assert slugify("Acme Outbound!") == "acme-outbound"
    assert slugify("  Café  Déjà  ") == "cafe-deja"
    assert slugify("///") == "workspace"

    assert unique_slug("Acme", taken=set()) == "acme"

    collision = unique_slug("Acme", taken={"acme"})
    assert collision.startswith("acme-") and collision != "acme"


def test_hash_token_is_stable_and_hex() -> None:
    digest = hash_token("abc")
    assert digest == hash_token("abc")
    assert len(digest) == 64
    assert digest != hash_token("abd")
