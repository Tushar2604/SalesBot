"""Encrypted persistence for LinkedIn sessions and in-flight challenges.

A stored `li_at` is full control of someone's LinkedIn account, so this module
is the only place that converts between a `SessionBundle` and bytes on disk.
Plaintext never crosses an API boundary and never reaches a log line.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.core.crypto import SecretCryptoError, decrypt_json, encrypt_json
from app.core.logging import get_logger
from app.linkedin.driver import ChallengeContext, SessionBundle
from app.models.linkedin import LinkedInAccount

log = get_logger(__name__)

# A challenge code is short-lived; a stale context must not be resumable.
CHALLENGE_TTL = timedelta(minutes=15)


def save_session(account: LinkedInAccount, session: SessionBundle) -> None:
    account.session_ciphertext = encrypt_json(session.to_dict())
    account.session_updated_at = datetime.now(UTC)
    # A fresh session invalidates any challenge that produced it.
    account.challenge_ciphertext = None
    account.challenge_expires_at = None


def load_session(account: LinkedInAccount) -> SessionBundle | None:
    """Returns the stored session, or None when absent or undecryptable.

    A decryption failure is logged and treated as "no session" rather than
    raised: the account simply needs reconnecting, which is the same remedy.
    """
    if not account.session_ciphertext:
        return None
    try:
        return SessionBundle.from_dict(decrypt_json(account.session_ciphertext))
    except (SecretCryptoError, KeyError, ValueError):
        log.error(
            "linkedin.session.undecryptable",
            account_id=str(account.id),
            hint="ENCRYPTION_KEY may have changed; the account must reconnect",
        )
        return None


def clear_session(account: LinkedInAccount) -> None:
    account.session_ciphertext = None
    account.session_updated_at = None


def save_challenge(account: LinkedInAccount, challenge: ChallengeContext) -> None:
    account.challenge_ciphertext = encrypt_json(challenge.to_dict())
    account.challenge_expires_at = datetime.now(UTC) + CHALLENGE_TTL


def load_challenge(account: LinkedInAccount) -> ChallengeContext | None:
    if not account.challenge_ciphertext:
        return None
    if account.challenge_expires_at and account.challenge_expires_at <= datetime.now(UTC):
        return None
    try:
        return ChallengeContext.from_dict(decrypt_json(account.challenge_ciphertext))
    except (SecretCryptoError, KeyError, ValueError):
        return None


def clear_challenge(account: LinkedInAccount) -> None:
    account.challenge_ciphertext = None
    account.challenge_expires_at = None
