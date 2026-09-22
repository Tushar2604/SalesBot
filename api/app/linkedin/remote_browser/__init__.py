"""Real, human-driven Chromium login sessions — see manager.py for the design.

Phase 1 scope: used only to establish a LinkedIn session. Once login succeeds
the extracted cookies are handed to the existing, unmodified
`linkedin.auth.connect_cookie` Celery task — every ongoing action still goes
through the httpx-based Voyager driver in `app.linkedin.voyager`.
"""

from __future__ import annotations

from app.linkedin.remote_browser.manager import (
    LaunchFailed,
    RemoteBrowserError,
    RemoteBrowserSession,
    SlotBusy,
    TooManyRemoteSessions,
    manager,
)

__all__ = [
    "LaunchFailed",
    "RemoteBrowserError",
    "RemoteBrowserSession",
    "SlotBusy",
    "TooManyRemoteSessions",
    "manager",
]
