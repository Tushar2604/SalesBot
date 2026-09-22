"""LinkedIn execution layer.

Import `build_driver` rather than a concrete driver: swapping the
implementation (browser session, third-party account API) must not require
changing callers.
"""

from __future__ import annotations

from app.config import settings
from app.linkedin import fingerprint, health, proxy, session_store
from app.linkedin.browser_driver import BrowserDriver
from app.linkedin.classify import Classification, ResponseClass, classify_response
from app.linkedin.driver import (
    ActionResult,
    AuthResult,
    ChallengeContext,
    ConversationSnapshot,
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
    """
    resolved = proxy.resolve(account.proxy)
    if settings.linkedin_driver == "browser":
        return BrowserDriver(
            fingerprint=account.fingerprint or {},
            proxy_url=resolved.url if resolved else None,
            session=session_store.load_session(account) if with_session else None,
            timeout=timeout,
            timezone=account.timezone or "UTC",
        )
    return MobileVoyagerDriver(
        fingerprint=account.fingerprint or fingerprint.generate(timezone=account.timezone),
        proxy_url=resolved.url if resolved else None,
        session=session_store.load_session(account) if with_session else None,
        timeout=timeout,
    )


__all__ = [
    "ActionResult",
    "AuthResult",
    "BrowserDriver",
    "ChallengeContext",
    "Classification",
    "ConversationSnapshot",
    "LinkedInDriver",
    "MobileVoyagerDriver",
    "ProfileSnapshot",
    "ResponseClass",
    "SearchPage",
    "SessionBundle",
    "build_driver",
    "classify_response",
    "fingerprint",
    "health",
    "proxy",
    "session_store",
]
