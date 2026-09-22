"""Account health and the circuit breaker.

One function, `apply_classification`, is the only way an account's safety state
changes in response to LinkedIn. Concentrating it here is what makes the policy
auditable — and the policy has one rule that must never be softened:

    **Never auto-retry into a block.**

A blocked, challenged, or de-authenticated account stops completely and waits
for a human. Retrying is how a temporary restriction becomes a permanent one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.logging import get_logger
from app.linkedin.classify import Classification, ResponseClass
from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus

log = get_logger(__name__)

# Back-off applied to a soft limit, before jitter.
SOFT_LIMIT_BACKOFF = timedelta(hours=6)
RATE_LIMIT_BACKOFF = timedelta(minutes=45)
TRANSPORT_BACKOFF = timedelta(minutes=10)

# Health deductions per class. Recovery is slow on purpose: an account that
# just tripped a limit should not be treated as fully healthy an hour later.
_HEALTH_PENALTY: dict[ResponseClass, int] = {
    ResponseClass.SOFT_LIMIT: 15,
    ResponseClass.RATE_LIMITED: 10,
    ResponseClass.AUTH_LOST: 40,
    ResponseClass.CHALLENGE: 30,
    ResponseClass.BLOCKED: 60,
    ResponseClass.UNKNOWN_SHAPE: 5,
    ResponseClass.TRANSPORT_ERROR: 2,
    ResponseClass.UPSTREAM_ERROR: 2,
}
_HEALTH_RECOVERY_PER_SUCCESS = 2


@dataclass(slots=True)
class HealthOutcome:
    """What the caller must do next."""

    circuit_opened: bool
    quota_should_halve: bool
    notify_user: bool
    status: LinkedInAccountStatus
    detail: str


def apply_classification(
    account: LinkedInAccount,
    classification: Classification,
    *,
    now: datetime | None = None,
) -> HealthOutcome:
    """Folds one LinkedIn response into the account's safety state.

    Mutates the account; the caller commits. Returns what else must happen
    (halving today's quota, notifying the customer) so those side effects stay
    in the task layer where they can be retried.
    """
    now = now or datetime.now(UTC)
    response_class = classification.response_class

    if response_class in {ResponseClass.OK, ResponseClass.NOT_FOUND}:
        account.consecutive_errors = 0
        account.health_score = min(100, account.health_score + _HEALTH_RECOVERY_PER_SUCCESS)
        account.last_action_at = now
        return HealthOutcome(
            circuit_opened=False,
            quota_should_halve=False,
            notify_user=False,
            status=account.status,
            detail="",
        )

    account.consecutive_errors += 1
    account.health_score = max(0, account.health_score - _HEALTH_PENALTY.get(response_class, 5))

    # ── the serious classes: stop, do not retry ──────────────────────────────
    if response_class.opens_circuit:
        status = {
            ResponseClass.AUTH_LOST: LinkedInAccountStatus.AUTH_LOST,
            ResponseClass.CHALLENGE: LinkedInAccountStatus.CHALLENGE,
            ResponseClass.BLOCKED: LinkedInAccountStatus.BLOCKED,
        }[response_class]

        account.status = status
        account.status_detail = classification.detail
        # No expiry: only a human clears this, by reconnecting or resolving the
        # challenge. A timed reopen would be an auto-retry into a block.
        account.circuit_open_until = now + timedelta(days=365)
        account.circuit_reason = f"{response_class.value}: {classification.detail}"[:200]

        log.error(
            "linkedin.circuit_opened",
            account_id=str(account.id),
            classification=response_class.value,
            detail=classification.detail,
        )
        return HealthOutcome(
            circuit_opened=True,
            quota_should_halve=False,
            notify_user=True,
            status=status,
            detail=classification.detail,
        )

    # ── recoverable classes: back off, stay connected ────────────────────────
    backoff = {
        ResponseClass.SOFT_LIMIT: SOFT_LIMIT_BACKOFF,
        ResponseClass.RATE_LIMITED: RATE_LIMIT_BACKOFF,
        ResponseClass.TRANSPORT_ERROR: TRANSPORT_BACKOFF,
        ResponseClass.UPSTREAM_ERROR: TRANSPORT_BACKOFF,
    }.get(response_class, timedelta(minutes=15))

    if classification.retry_after_seconds:
        backoff = max(backoff, timedelta(seconds=classification.retry_after_seconds))

    account.next_allowed_at = now + backoff
    account.status_detail = classification.detail

    # Repeated unexplained failures are treated as a risk signal even when each
    # one looks benign: something is wrong that we cannot name.
    if account.consecutive_errors >= 8:
        account.circuit_open_until = now + timedelta(hours=12)
        account.circuit_reason = (
            f"{account.consecutive_errors} consecutive errors, last: {response_class.value}"
        )[:200]
        log.error(
            "linkedin.circuit_opened.error_streak",
            account_id=str(account.id),
            consecutive_errors=account.consecutive_errors,
        )
        return HealthOutcome(
            circuit_opened=True,
            quota_should_halve=True,
            notify_user=True,
            status=account.status,
            detail=f"paused after {account.consecutive_errors} consecutive errors",
        )

    return HealthOutcome(
        circuit_opened=False,
        quota_should_halve=response_class is ResponseClass.SOFT_LIMIT,
        notify_user=False,
        status=account.status,
        detail=classification.detail,
    )


def can_dispatch(account: LinkedInAccount, *, now: datetime | None = None) -> tuple[bool, str]:
    """Gate consulted before every action. Returns (allowed, reason_if_not)."""
    now = now or datetime.now(UTC)

    if not account.status.is_operable:
        return False, f"account status is {account.status.value}"
    if account.circuit_is_open(now):
        return False, f"circuit open: {account.circuit_reason or 'unknown'}"
    if account.next_allowed_at is not None and account.next_allowed_at > now:
        return False, "pacing: next action not due yet"
    if account.session_ciphertext is None:
        return False, "no stored session"
    return True, ""
