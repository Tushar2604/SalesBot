"""Frozen desktop-browser identity for a remote-browser login session.

Sibling to `app.linkedin.fingerprint`, not a reuse of it: that module draws an
Android *mobile app* identity (client version, device id, no user-agent or
viewport at all) for the httpx-based Voyager driver. A real Chromium session
is a different LinkedIn surface entirely — trying to make it impersonate the
mobile app's identity would itself look wrong. This draws a coherent desktop
*browser* identity instead, drawn once per account and frozen for life, stored
alongside the mobile fingerprint under a separate key so no migration is
needed.
"""

from __future__ import annotations

import random
from typing import Any, Final, TypedDict

# Coherent desktop profiles: a real, currently-shipping Chrome build, a matching
# platform string, and a screen size real hardware actually ships with. Mixing
# fields across profiles (e.g. a Mac UA with a Windows platform) is exactly the
# kind of incoherence bot detection is built to catch.
_BROWSER_PROFILES: Final[list[dict[str, Any]]] = [
    {
        "chrome_version": "128.0.6613.120",
        "platform": "Win32",
        "os_label": "Windows NT 10.0; Win64; x64",
        "viewport": {"width": 1920, "height": 1080},
    },
    {
        "chrome_version": "128.0.6613.138",
        "platform": "Win32",
        "os_label": "Windows NT 10.0; Win64; x64",
        "viewport": {"width": 1536, "height": 864},
    },
    {
        "chrome_version": "127.0.6533.100",
        "platform": "MacIntel",
        "os_label": "Macintosh; Intel Mac OS X 10_15_7",
        "viewport": {"width": 1440, "height": 900},
    },
    {
        "chrome_version": "128.0.6613.120",
        "platform": "Win32",
        "os_label": "Windows NT 10.0; Win64; x64",
        "viewport": {"width": 1366, "height": 768},
    },
]


class Viewport(TypedDict):
    width: int
    height: int


def generate(*, locale: str = "en-US", timezone: str = "UTC") -> dict[str, Any]:
    """Draws a new frozen desktop-browser identity.

    Call exactly once per LinkedIn account, the first time a remote-browser
    session is started for it. The result is stored under
    `linkedin_accounts.fingerprint["browser"]` — never regenerated afterward.
    """
    profile = random.choice(_BROWSER_PROFILES)  # noqa: S311 - not a security decision
    return {
        "schema": 1,
        "chrome_version": profile["chrome_version"],
        "platform": profile["platform"],
        "os_label": profile["os_label"],
        "viewport": dict(profile["viewport"]),
        "locale": locale,
        "timezone": timezone,
    }


def user_agent(fp: dict[str, Any]) -> str:
    """The Chrome desktop User-Agent assembled from the frozen profile."""
    version = str(fp.get("chrome_version", "128.0.0.0"))
    os_label = str(fp.get("os_label", "Windows NT 10.0; Win64; x64"))
    return (
        f"Mozilla/5.0 ({os_label}) AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{version} Safari/537.36"
    )


def viewport(fp: dict[str, Any]) -> Viewport:
    raw = fp.get("viewport") or {"width": 1440, "height": 900}
    return Viewport(width=int(raw["width"]), height=int(raw["height"]))


def describe(fp: dict[str, Any]) -> str:
    """Short human-readable summary for the UI and audit log. No secrets."""
    if not fp:
        return "not assigned"
    vp = viewport(fp)
    return (
        f"Chrome {fp.get('chrome_version', '?')} · {fp.get('platform', '?')} · "
        f"{vp['width']}x{vp['height']}"
    )
