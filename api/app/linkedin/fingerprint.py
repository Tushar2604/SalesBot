"""Per-account device identity.

LinkedIn's mobile clients announce themselves with a set of mutually-consistent
headers: a client version, a device model, display metrics, a locale, and a
stable device id. Incoherent combinations (a phone model with a tablet's screen,
a client version that never shipped for that OS) are cheap to detect.

So a fingerprint is drawn **once** from a catalogue of real device profiles,
persisted on the account row, and never regenerated. Rotation is the anomaly:
a real phone does not change model between sessions.

Everything here is deterministic given a stored dict, which is what makes the
frozen-identity guarantee testable.
"""

from __future__ import annotations

import random
import uuid
from typing import Any, Final

# Coherent device profiles: model name, Android release/API level, and the
# display metrics that actually ship with that device.
_DEVICE_PROFILES: Final[list[dict[str, Any]]] = [
    {
        "model": "Google_Pixel 7",
        "marketing_name": "Pixel 7",
        "android_release": "14",
        "os_version": "34",
        "build_id": "UQ1A.240205.004",
        "display_width": 1080,
        "display_height": 2400,
        "display_density": 2.625,
        "dpi": "xxhdpi",
    },
    {
        "model": "Google_Pixel 8",
        "marketing_name": "Pixel 8",
        "android_release": "14",
        "os_version": "34",
        "build_id": "AP1A.240505.004",
        "display_width": 1080,
        "display_height": 2400,
        "display_density": 2.625,
        "dpi": "xxhdpi",
    },
    {
        "model": "samsung_SM-S911B",
        "marketing_name": "Galaxy S23",
        "android_release": "14",
        "os_version": "34",
        "build_id": "UP1A.231005.007",
        "display_width": 1080,
        "display_height": 2340,
        "display_density": 3.0,
        "dpi": "xxhdpi",
    },
    {
        "model": "samsung_SM-A546B",
        "marketing_name": "Galaxy A54",
        "android_release": "13",
        "os_version": "33",
        "build_id": "TP1A.220624.014",
        "display_width": 1080,
        "display_height": 2340,
        "display_density": 2.625,
        "dpi": "xxhdpi",
    },
    {
        "model": "OnePlus_CPH2449",
        "marketing_name": "OnePlus 11",
        "android_release": "13",
        "os_version": "33",
        "build_id": "TP1A.220905.001",
        "display_width": 1440,
        "display_height": 3216,
        "display_density": 3.5,
        "dpi": "xxxhdpi",
    },
]

# Plausible recent client versions. Kept as a small range so an account's
# version stays inside the window LinkedIn still serves.
_CLIENT_VERSIONS: Final[list[str]] = [
    "4.1.916",
    "4.1.920",
    "4.1.924",
    "4.1.928",
]

APP_ID: Final[str] = "com.linkedin.android"
RESTLI_PROTOCOL_VERSION: Final[str] = "2.0.0"


def generate(*, locale: str = "en_US", timezone: str = "UTC") -> dict[str, Any]:
    """Draws a new frozen device identity.

    Call exactly once per LinkedIn account, at connect time. The returned dict
    is stored verbatim on `linkedin_accounts.fingerprint`.
    """
    device = random.choice(_DEVICE_PROFILES)  # noqa: S311 - not a security decision
    client_version = random.choice(_CLIENT_VERSIONS)  # noqa: S311

    return {
        "schema": 1,
        "client_version": client_version,
        "app_id": APP_ID,
        "device_id": str(uuid.uuid4()),
        "locale": locale,
        "timezone": timezone,
        **device,
    }


def user_agent(fp: dict[str, Any]) -> str:
    """The Android app's User-Agent, assembled from the frozen profile."""
    model = str(fp.get("marketing_name") or fp.get("model", "Pixel 7"))
    return (
        f"com.linkedin.android/{fp['client_version']} "
        f"(Linux; U; Android {fp['android_release']}; {fp.get('locale', 'en_US')}; "
        f"{model}; Build/{fp['build_id']})"
    )


def li_track(fp: dict[str, Any]) -> dict[str, Any]:
    """The `x-li-track` payload LinkedIn's mobile clients attach to every call."""
    return {
        "clientVersion": fp["client_version"],
        "mpVersion": fp["client_version"],
        "osName": "Android OS",
        "osVersion": str(fp["os_version"]),
        "clientMinorVersion": 0,
        "model": fp["model"],
        "displayDensity": fp["display_density"],
        "displayWidth": fp["display_width"],
        "displayHeight": fp["display_height"],
        "dpi": fp["dpi"],
        "deviceFormFactor": "PHONE",
        "isAdTrackingLimited": False,
        "appId": fp.get("app_id", APP_ID),
    }


def describe(fp: dict[str, Any]) -> str:
    """Short human-readable summary for the UI and audit log. No secrets."""
    if not fp:
        return "not assigned"
    return (
        f"{fp.get('marketing_name', fp.get('model', 'unknown'))} · "
        f"Android {fp.get('android_release', '?')} · app {fp.get('client_version', '?')}"
    )
