"""Authentication tasks. These run in a worker so the session is established
from the account's own proxy, never from the API process.

Every task follows the same shape: load the account, build its driver, act,
fold the result into health state, commit. The driver is always closed, because
each one holds a proxy connection.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt_json
from app.core.logging import get_logger
from app.db import session_scope
from app.linkedin import build_driver, health, session_store
from app.linkedin.driver import AuthResult, ProfileSnapshot
from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus
from app.models.tenancy import NotificationType
from app.services import audit, notification_service
from app.worker.celery_app import celery_app

log = get_logger(__name__)


def _unseal(sealed: str) -> dict[str, Any]:
    return decrypt_json(base64.b64decode(sealed))


def _load(db: Session, account_id: str) -> LinkedInAccount | None:
    account = db.get(LinkedInAccount, account_id)
    if account is None:
        log.error("linkedin.auth.account_missing", account_id=account_id)
    return account


def _adopt_profile(account: LinkedInAccount, profile: ProfileSnapshot) -> None:
    """Records who LinkedIn says we are signed in as."""
    account.profile_urn = profile.urn or account.profile_urn
    account.public_id = profile.public_id or account.public_id
    account.full_name = profile.full_name or account.full_name
    account.headline = profile.headline or account.headline
    account.avatar_url = profile.avatar_url or account.avatar_url
    if profile.country:
        account.profile_country = profile.country[:2].upper()
    if not account.label or account.label == account.login_email:
        account.label = profile.full_name or account.label


def _disconnect_duplicates(db: Session, account: LinkedInAccount, profile_urn: str) -> int:
    """Disconnects any other row in this workspace already resolved to `profile_urn`.

    The email pre-check in `linkedin_service.create_account` only catches a
    repeat connect with the *same* email — it can't see a cookie-based connect
    (no email at all) or a credentials connect against an email that differs
    from one already used for this same LinkedIn profile. This is the
    authoritative dedup: LinkedIn's own confirmed identity, known only once
    sign-in succeeds. The most recently signed-in row wins; older duplicates
    are disconnected rather than deleted, so their history survives under
    their own id.

    Takes the target urn as a parameter and must run — with its own flush —
    *before* the caller assigns `profile_urn` onto `account`: the unique
    constraint on `(workspace_id, profile_urn)` isn't deferrable, so a
    duplicate's old claim has to actually hit the database as cleared before
    the surviving row's UPDATE can claim the same value.
    """
    if not profile_urn:
        return 0

    duplicates = (
        db.execute(
            select(LinkedInAccount).where(
                LinkedInAccount.workspace_id == account.workspace_id,
                LinkedInAccount.id != account.id,
                LinkedInAccount.profile_urn == profile_urn,
            )
        )
        .scalars()
        .all()
    )
    for duplicate in duplicates:
        session_store.clear_session(duplicate)
        session_store.clear_challenge(duplicate)
        duplicate.status = LinkedInAccountStatus.DISCONNECTED
        duplicate.status_detail = "superseded by a newer connection of the same LinkedIn account"
        # Free the identity so the surviving row's own UPDATE (a few lines
        # below, in a later flush) can safely claim it.
        duplicate.profile_urn = None
        duplicate.circuit_open_until = None
        duplicate.circuit_reason = ""
        duplicate.consecutive_errors = 0
        audit.record_sync(
            db,
            "linkedin_account.duplicate_disconnected",
            workspace_id=duplicate.workspace_id,
            target_type="linkedin_account",
            target_id=duplicate.id,
            metadata={"superseded_by": str(account.id), "public_id": account.public_id},
        )
        log.info(
            "linkedin.auth.duplicate_disconnected",
            account_id=str(duplicate.id),
            superseded_by=str(account.id),
        )
    if duplicates:
        db.flush()
    return len(duplicates)


def _finalize(db: Session, account: LinkedInAccount, result: AuthResult, *, source: str) -> str:
    """Applies an auth outcome to the account. Returns the resulting status."""
    now = datetime.now(UTC)

    if result.ok and result.session is not None:
        session_store.save_session(account, result.session)
        account.status = LinkedInAccountStatus.ACTIVE
        account.status_detail = ""
        account.circuit_open_until = None
        account.circuit_reason = ""
        account.consecutive_errors = 0
        account.health_score = max(account.health_score, 80)
        if account.ramp_started_at is None:
            account.ramp_started_at = now

        # Confirm identity on the session we just established.
        driver = build_driver(account)
        try:
            classification, profile = driver.verify_session()
            if classification.ok and profile is not None:
                # Now that LinkedIn has confirmed who this is, this is the one
                # place that can reliably tell a re-connect of the same
                # profile from a genuinely new account — collapse any
                # duplicates onto this row before claiming the identity.
                _disconnect_duplicates(db, account, profile.urn)
                _adopt_profile(account, profile)
        finally:
            driver.close()

        audit.record_sync(
            db,
            "linkedin_account.connected",
            workspace_id=account.workspace_id,
            target_type="linkedin_account",
            target_id=account.id,
            metadata={"source": source, "public_id": account.public_id},
        )
        log.info(
            "linkedin.auth.connected",
            account_id=str(account.id),
            source=source,
            public_id=account.public_id,
        )
        return account.status.value

    # A challenge is not a failure: it is a state the user can resolve.
    if result.needs_challenge and result.challenge is not None:
        session_store.save_challenge(account, result.challenge)
        account.status = (
            LinkedInAccountStatus.PENDING_2FA
            if result.challenge.kind == "2fa"
            else LinkedInAccountStatus.PENDING_EMAIL_PIN
            if result.challenge.kind == "email_pin"
            else LinkedInAccountStatus.CHALLENGE
        )
        account.status_detail = (
            result.classification.detail or "LinkedIn asked for a verification code"
        )
        audit.record_sync(
            db,
            "linkedin_account.challenge_raised",
            workspace_id=account.workspace_id,
            target_type="linkedin_account",
            target_id=account.id,
            metadata={"kind": result.challenge.kind, "source": source},
        )
        notification_service.create_sync(
            db,
            account.workspace_id,
            NotificationType.ACCOUNT_ACTION_NEEDED,
            f"Verification needed for {account.label or account.public_id or 'a LinkedIn account'}",
            body=account.status_detail,
            link="/accounts",
        )
        return account.status.value

    # Genuine failure — let the health module decide the consequences.
    outcome = health.apply_classification(account, result.classification, now=now)
    if not outcome.circuit_opened:
        # Failed sign-in with no session leaves the account disconnected rather
        # than in a half-connected state.
        account.status = LinkedInAccountStatus.AUTH_LOST
        account.status_detail = result.classification.detail or "sign-in failed"

    audit.record_sync(
        db,
        "linkedin_account.connect_failed",
        workspace_id=account.workspace_id,
        target_type="linkedin_account",
        target_id=account.id,
        metadata={
            "source": source,
            "classification": result.classification.response_class.value,
            "detail": result.classification.detail,
        },
    )
    log.warning(
        "linkedin.auth.failed",
        account_id=str(account.id),
        source=source,
        classification=result.classification.response_class.value,
        detail=result.classification.detail,
    )
    return account.status.value


@celery_app.task(name="linkedin.auth.connect_cookie", bind=True, max_retries=0)
def connect_cookie(self: Any, account_id: str, sealed: str) -> dict[str, str]:
    """Adopt a session cookie the user supplied.

    `max_retries=0` throughout this module: a retried sign-in is a second login
    attempt, which is itself a risk signal. Failures surface to the user.
    """
    _ = self
    secrets = _unseal(sealed)

    with session_scope() as db:
        account = _load(db, account_id)
        if account is None:
            return {"status": "missing"}

        driver = build_driver(account, with_session=False)
        try:
            result = driver.authenticate_with_cookie(
                secrets["li_at"],
                secrets.get("jsessionid") or None,
                cookies=secrets.get("cookies") or None,
            )
        finally:
            driver.close()

        return {"status": _finalize(db, account, result, source="cookie")}


@celery_app.task(name="linkedin.auth.connect_credentials", bind=True, max_retries=0)
def connect_credentials(self: Any, account_id: str, sealed: str) -> dict[str, str]:
    """Sign in with email and password from the account's proxy."""
    _ = self
    secrets = _unseal(sealed)

    with session_scope() as db:
        account = _load(db, account_id)
        if account is None:
            return {"status": "missing"}

        driver = build_driver(account, with_session=False)
        try:
            result = driver.authenticate_with_credentials(secrets["email"], secrets["password"])
        finally:
            driver.close()
            # Drop the plaintext as soon as LinkedIn has answered.
            secrets.clear()

        return {"status": _finalize(db, account, result, source="credentials")}


@celery_app.task(name="linkedin.auth.submit_challenge", bind=True, max_retries=0)
def submit_challenge(self: Any, account_id: str, sealed: str) -> dict[str, str]:
    """Submit a verification code against the session that raised the challenge."""
    _ = self
    secrets = _unseal(sealed)

    with session_scope() as db:
        account = _load(db, account_id)
        if account is None:
            return {"status": "missing"}

        challenge = session_store.load_challenge(account)
        if challenge is None:
            account.status = LinkedInAccountStatus.AUTH_LOST
            account.status_detail = "The verification window expired. Start the connection again."
            return {"status": account.status.value}

        driver = build_driver(account, with_session=False)
        try:
            result = driver.submit_challenge(challenge, secrets["code"])
        finally:
            driver.close()
            secrets.clear()

        return {"status": _finalize(db, account, result, source="challenge")}


@celery_app.task(name="linkedin.auth.verify", bind=True, max_retries=0)
def verify(self: Any, account_id: str) -> dict[str, str]:
    """Liveness probe for a connected account.

    Run on demand from the UI and periodically by Beat. This is how an expired
    session is discovered before a campaign tries to use it.
    """
    _ = self
    with session_scope() as db:
        account = _load(db, account_id)
        if account is None:
            return {"status": "missing"}

        if not account.is_connected:
            return {"status": account.status.value, "classification": "no_session"}

        driver = build_driver(account)
        try:
            classification, profile = driver.verify_session()
        finally:
            driver.close()

        if classification.ok and profile is not None:
            _disconnect_duplicates(db, account, profile.urn)
            _adopt_profile(account, profile)
            if account.status in {
                LinkedInAccountStatus.AUTH_LOST,
                LinkedInAccountStatus.CONNECTING,
            }:
                account.status = LinkedInAccountStatus.ACTIVE
                account.status_detail = ""
            health.apply_classification(account, classification)
        else:
            outcome = health.apply_classification(account, classification)
            log.warning(
                "linkedin.verify.failed",
                account_id=account_id,
                classification=classification.response_class.value,
                circuit_opened=outcome.circuit_opened,
            )
            if outcome.circuit_opened:
                who = account.label or account.public_id or "A LinkedIn account"
                notification_service.create_sync(
                    db,
                    account.workspace_id,
                    NotificationType.ACCOUNT_ACTION_NEEDED,
                    f"{who} stopped — {outcome.status.value.replace('_', ' ')}",
                    body=outcome.detail
                    or "Outreach from this account is paused until you reconnect it.",
                    link="/accounts",
                )

        return {
            "status": account.status.value,
            "classification": classification.response_class.value,
            "detail": classification.detail,
        }


@celery_app.task(name="linkedin.sync.verify_all")
def verify_all() -> dict[str, int]:
    """Beat job: probe every connected account's session.

    Spread out rather than fired at once — a thousand accounts all calling
    LinkedIn in the same second is a pattern in itself.
    """
    from sqlalchemy import select

    queued = 0
    with session_scope() as db:
        stmt = select(LinkedInAccount.id).where(
            LinkedInAccount.status.in_(
                [LinkedInAccountStatus.ACTIVE, LinkedInAccountStatus.PAUSED]
            ),
            LinkedInAccount.session_ciphertext.isnot(None),
        )
        account_ids = list(db.execute(stmt).scalars().all())

    for index, account_id in enumerate(account_ids):
        verify.apply_async(args=[str(account_id)], countdown=index * 7)
        queued += 1

    log.info("linkedin.verify_all.queued", count=queued)
    return {"queued": queued}
