"""Per-account volume limits and the ramp-up curve.

Limits are resolved here, never read straight off the account row, because two
rules must hold no matter what the UI sends:

1. A stored cap may only ever be *more* conservative than the configured
   ceiling. A tenant cannot raise their own limits past what is safe.
2. A young account is capped by its ramp curve regardless of its stored cap.
   Connecting an account and immediately sending 75 invites is the single most
   reliable way to get restricted.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.config import settings
from app.models.linkedin import LinkedInAccount

# Days since connect -> ceiling on invites/day. The last entry applies onward.
_RAMP_CURVE: tuple[tuple[int, int], ...] = (
    (0, 12),  # week 1
    (7, 25),  # week 2
    (14, 40),  # week 3
    (21, 75),  # week 4+: the plan cap takes over
)

DEFAULT_WORKING_HOURS = {"start": "09:00", "end": "17:30"}


def default_caps() -> dict[str, Any]:
    """Caps a newly connected account starts with. Deliberately conservative."""
    return {
        "daily_invites": settings.safety_test_mode_daily_invites
        if settings.safety_default_test_mode
        else 20,
        "daily_messages": 20,
        "daily_views": 30,
        "weekly_invites": settings.safety_max_weekly_invites,
        "working_hours": dict(DEFAULT_WORKING_HOURS),
        "weekdays_only": True,
    }


def warmup_invites(account: LinkedInAccount, *, now: datetime) -> int:
    """Warm-up invites/day: a stable per-account, per-day pick in the configured range.

    Deterministic (hash, not random) so every dispatcher tick within a day sees
    the same number, while different days and accounts differ.
    """
    low = settings.safety_test_mode_daily_invites
    high = max(low, settings.safety_test_mode_daily_invites_max)
    digest = hashlib.sha256(f"{account.id}:{now.date().isoformat()}".encode()).digest()
    return low + digest[0] % (high - low + 1)


def ramp_ceiling(account: LinkedInAccount, *, now: datetime | None = None) -> int:
    """Invites/day allowed by the ramp curve alone."""
    now = now or datetime.now(UTC)
    started = account.ramp_started_at or account.created_at or now
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)

    age_days = max(0, (now - started).days)
    ceiling = _RAMP_CURVE[0][1]
    for threshold, value in _RAMP_CURVE:
        if age_days >= threshold:
            ceiling = value
    return ceiling


@dataclass(slots=True)
class EffectiveCaps:
    daily_invites: int
    daily_messages: int
    daily_views: int
    weekly_invites: int
    working_hours: tuple[time, time]
    weekdays_only: bool
    timezone: str
    # Why the invite number ended up where it did — shown in the UI so the
    # limit never looks arbitrary.
    invite_limit_reason: str


def _parse_time(value: Any, fallback: time) -> time:
    try:
        hour, minute = str(value).split(":")
        return time(int(hour), int(minute))
    except (ValueError, AttributeError):
        return fallback


def resolve(account: LinkedInAccount, *, now: datetime | None = None) -> EffectiveCaps:
    """The limits actually in force for this account right now."""
    now = now or datetime.now(UTC)
    stored = account.caps or {}

    requested_invites = int(stored.get("daily_invites", settings.safety_test_mode_daily_invites))
    ramp = ramp_ceiling(account, now=now)
    ceiling = settings.safety_max_daily_invites

    candidates = [
        (requested_invites, "your configured limit"),
        (ramp, "account warm-up curve"),
        (ceiling, "platform safety ceiling"),
    ]
    if account.test_mode:
        candidates.append((warmup_invites(account, now=now), "test mode"))

    daily_invites, reason = min(candidates, key=lambda pair: pair[0])

    daily_messages = min(int(stored.get("daily_messages", 20)), 75)
    if account.test_mode:
        daily_messages = min(daily_messages, settings.safety_test_mode_daily_messages)

    hours = stored.get("working_hours") or DEFAULT_WORKING_HOURS
    return EffectiveCaps(
        daily_invites=daily_invites,
        daily_messages=daily_messages,
        daily_views=min(int(stored.get("daily_views", 30)), 150),
        weekly_invites=min(
            int(stored.get("weekly_invites", settings.safety_max_weekly_invites)),
            settings.safety_max_weekly_invites,
        ),
        working_hours=(
            _parse_time(hours.get("start"), time(9, 0)),
            _parse_time(hours.get("end"), time(17, 30)),
        ),
        weekdays_only=bool(stored.get("weekdays_only", True)),
        timezone=account.timezone or "UTC",
        invite_limit_reason=reason,
    )


def zone_for(account: LinkedInAccount) -> ZoneInfo:
    """The account's own timezone, which is what working hours are measured in."""
    try:
        return ZoneInfo(account.timezone or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def within_working_hours(
    account: LinkedInAccount, *, now: datetime | None = None
) -> tuple[bool, str]:
    """Whether the account may act at this moment, in its *own* local time."""
    now = now or datetime.now(UTC)
    caps = resolve(account, now=now)
    local = now.astimezone(zone_for(account))

    if caps.weekdays_only and local.weekday() >= 5:
        return False, "outside working days (weekend in the account's timezone)"

    start, end = caps.working_hours
    if not (start <= local.time() <= end):
        return False, (
            f"outside working hours {start:%H:%M}-{end:%H:%M} "
            f"({local:%H:%M} local in {caps.timezone})"
        )
    return True, ""


def week_window(now: datetime | None = None) -> tuple[date, date]:
    """Trailing 7-day window used for the rolling invite cap."""
    now = now or datetime.now(UTC)
    today = now.date()
    return today - timedelta(days=6), today
