"""LinkedIn execution layer.

Import `build_driver` rather than a concrete driver: swapping the
implementation (browser session, third-party account API) must not require
changing callers.
"""

from __future__ import annotations

from typing import cast

from app.config import settings
from app.linkedin import fingerprint, guard, health, proxy, session_store
from app.linkedin.browser_driver import BrowserDriver
from app.linkedin.classify import Classification, ResponseClass, classify_response
from app.linkedin.driver import (
    ActionResult,
    AuthResult,
    ChallengeContext,
    ConversationSnapshot,
    FeedPost,
    LinkedInDriver,
    ProfileSnapshot,
    SearchPage,
    SessionBundle,
)
from app.linkedin.voyager import MobileVoyagerDriver
from app.models.linkedin import LinkedInAccount


def build_driver(
    account: LinkedInAccount,
    *,
    with_session: bool = True,
    timeout: float = 30.0,
) -> LinkedInDriver:
    """Constructs the driver for one account.

    Binds together the three pieces that must always travel together: the
    frozen fingerprint, the assigned proxy, and the stored session. Building
    them separately at a call site is how they drift apart.

    The driver comes wrapped in the action gap guard: every write it makes
    waits out the account's human-like gap, whoever the caller is (see
    app/linkedin/guard.py). This is the only place a driver is constructed.
    """
    resolved = proxy.resolve(account.proxy)
    inner: LinkedInDriver
    if settings.linkedin_driver == "browser":
        inner = BrowserDriver(
            fingerprint=account.fingerprint or {},
            proxy_url=resolved.url if resolved else None,
            session=session_store.load_session(account) if with_session else None,
            timeout=timeout,
            timezone=account.timezone or "UTC",
            profile_account_id=account.id,
        )
    else:
        inner = MobileVoyagerDriver(
            fingerprint=account.fingerprint or fingerprint.generate(timezone=account.timezone),
            proxy_url=resolved.url if resolved else None,
            session=session_store.load_session(account) if with_session else None,
            timeout=timeout,
        )
    return cast(LinkedInDriver, guard.GuardedDriver(inner, account))


__all__ = [
    "ActionResult",
    "AuthResult",
    "BrowserDriver",
    "ChallengeContext",
    "Classification",
    "ConversationSnapshot",
    "FeedPost",
    "LinkedInDriver",
    "MobileVoyagerDriver",
    "ProfileSnapshot",
    "ResponseClass",
    "SearchPage",
    "SessionBundle",
    "build_driver",
    "classify_response",
    "fingerprint",
    "guard",
    "health",
    "proxy",
    "session_store",
]
