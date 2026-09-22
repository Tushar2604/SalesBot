"""Response classification — the input to every safety decision.

Every HTTP response from LinkedIn is reduced to one of a handful of classes. The
dispatcher and the circuit breaker act on the class, never on a raw status code,
so the policy ("never auto-retry into a block") lives in one place.

`UNKNOWN_SHAPE` is deliberate and load-bearing: a response we cannot parse means
LinkedIn changed something. Counted across accounts it is the drift alarm that
tells an operator to look before customers notice.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any


class ResponseClass(enum.StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    # recoverable: back off, halve the day's remaining quota
    SOFT_LIMIT = "soft_limit"
    RATE_LIMITED = "rate_limited"
    # session is gone; needs the user to reconnect
    AUTH_LOST = "auth_lost"
    # LinkedIn wants a human to prove something
    CHALLENGE = "challenge"
    # account restricted — the serious one
    BLOCKED = "blocked"
    # transport/proxy failure, safe to retry later
    TRANSPORT_ERROR = "transport_error"
    # we could not understand the response
    UNKNOWN_SHAPE = "unknown_shape"
    UPSTREAM_ERROR = "upstream_error"

    @property
    def opens_circuit(self) -> bool:
        """Classes that must stop all activity on the account immediately."""
        return self in {
            ResponseClass.AUTH_LOST,
            ResponseClass.CHALLENGE,
            ResponseClass.BLOCKED,
        }

    @property
    def is_retryable(self) -> bool:
        return self in {
            ResponseClass.RATE_LIMITED,
            ResponseClass.SOFT_LIMIT,
            ResponseClass.TRANSPORT_ERROR,
            ResponseClass.UPSTREAM_ERROR,
        }


@dataclass(slots=True)
class Classification:
    response_class: ResponseClass
    detail: str = ""
    # Set when LinkedIn told us how long to wait.
    retry_after_seconds: int | None = None
    # Present for CHALLENGE: where the user must go, or what to submit.
    challenge_url: str = ""
    challenge_kind: str = ""

    @property
    def ok(self) -> bool:
        return self.response_class is ResponseClass.OK


# Substrings LinkedIn serves on its restriction and checkpoint pages. Matched
# case-insensitively against the body; kept as data so a change is a one-line fix.
_BLOCKED_MARKERS: tuple[str, ...] = (
    "unusual activity",
    "account has been restricted",
    "account restricted",
    "we've restricted your account",
    "temporarily restricted",
)

_CHALLENGE_MARKERS: tuple[str, ...] = (
    "checkpoint/challenge",
    "challenge-page",
    "two-step verification",
    "verify your identity",
    "captcha",
)

_SOFT_LIMIT_MARKERS: tuple[str, ...] = (
    "you've reached the weekly invitation limit",
    "weekly invitation limit",
    "reached the maximum number of invitations",
    "invitation limit",
    "too many requests",
)

_AUTH_MARKERS: tuple[str, ...] = (
    "csrf",
    "not authenticated",
    "session expired",
)

# Redirect targets. An authenticated Voyager call never redirects, so where it
# points is the whole diagnosis.
_LOGIN_REDIRECTS: tuple[str, ...] = (
    "/login",
    "/authwall",
    "/uas/login",
    "/uas/authenticate",
    "signup/",
)


def _contains(haystack: str, needles: tuple[str, ...]) -> str:
    lowered = haystack.lower()
    for needle in needles:
        if needle in lowered:
            return needle
    return ""


def classify_response(
    *,
    status_code: int,
    body: str,
    final_url: str = "",
    payload: dict[str, Any] | None = None,
    redirect_location: str = "",
) -> Classification:
    """Reduces one LinkedIn response to a safety class.

    Order matters: the most serious interpretation wins, because misreading a
    block as a rate limit would mean retrying into it.
    """
    # A checkpoint redirect is a challenge regardless of status code.
    for candidate in (final_url, redirect_location):
        if "checkpoint/challenge" in candidate.lower():
            return Classification(
                ResponseClass.CHALLENGE,
                detail="redirected to a LinkedIn checkpoint",
                challenge_url=candidate,
            )

    # An authenticated Voyager call never redirects. Being sent to the login
    # wall means the session is gone — not a transport problem to retry, which
    # is exactly the misreading that would cause repeated pointless sign-ins.
    if 300 <= status_code < 400:
        if _contains(redirect_location, _LOGIN_REDIRECTS):
            return Classification(
                ResponseClass.AUTH_LOST,
                detail="LinkedIn redirected to its login page: the session is not valid",
            )
        # LinkedIn bounces unauthenticated API calls with a bare 302 carrying no
        # Location header at all. An authenticated Voyager call never redirects,
        # so on an API path this is a dead session, not drift.
        if "/voyager/api" in final_url.lower():
            return Classification(
                ResponseClass.AUTH_LOST,
                detail="LinkedIn rejected the session on an API call (HTTP 302)",
            )
        return Classification(
            ResponseClass.UNKNOWN_SHAPE,
            detail=f"unexpected redirect to {redirect_location or final_url!r}",
        )

    # 999 is LinkedIn's own "we don't like this traffic" code.
    if status_code == 999:
        return Classification(
            ResponseClass.BLOCKED, detail="LinkedIn returned 999 (request denied)"
        )

    if marker := _contains(body, _BLOCKED_MARKERS):
        return Classification(ResponseClass.BLOCKED, detail=f"restriction page matched {marker!r}")

    if marker := _contains(body, _CHALLENGE_MARKERS):
        return Classification(
            ResponseClass.CHALLENGE,
            detail=f"challenge page matched {marker!r}",
            challenge_url=final_url,
        )

    if status_code in (401, 403):
        # 403 with a CSRF complaint is a dead session, not a permission problem.
        if _contains(body, _AUTH_MARKERS) or status_code == 401:
            return Classification(
                ResponseClass.AUTH_LOST, detail=f"HTTP {status_code}: session no longer valid"
            )
        return Classification(ResponseClass.AUTH_LOST, detail=f"HTTP {status_code}")

    if status_code == 429:
        return Classification(
            ResponseClass.RATE_LIMITED, detail="HTTP 429 from LinkedIn", retry_after_seconds=None
        )

    if marker := _contains(body, _SOFT_LIMIT_MARKERS):
        return Classification(ResponseClass.SOFT_LIMIT, detail=f"limit notice matched {marker!r}")

    if status_code == 404:
        return Classification(ResponseClass.NOT_FOUND, detail="HTTP 404")

    if 500 <= status_code < 600:
        return Classification(ResponseClass.UPSTREAM_ERROR, detail=f"HTTP {status_code}")

    if 200 <= status_code < 300:
        # A 200 that should carry JSON but does not is drift, not success.
        if payload is None and body and not body.lstrip().startswith(("{", "[")):
            return Classification(
                ResponseClass.UNKNOWN_SHAPE,
                detail="2xx response was not JSON where JSON was expected",
            )
        return Classification(ResponseClass.OK)

    return Classification(ResponseClass.UNKNOWN_SHAPE, detail=f"unhandled HTTP {status_code}")
