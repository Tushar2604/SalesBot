"""Action pacing.

Delays are drawn from a **log-normal** distribution, not a uniform one. That is
not decoration: uniform jitter produces a flat histogram, which is itself a
machine signature. Human inter-action gaps are right-skewed — mostly short,
occasionally very long — and log-normal reproduces that shape.

Everything here is a pure function of (config, RNG), so the distribution is
testable without a clock or a database.
"""

from __future__ import annotations

import math
import random
from datetime import UTC, date, datetime, time, timedelta

from app.config import settings
from app.linkedin import caps as caps_mod
from app.models.linkedin import LinkedInAccount

_DEFAULT_RNG = random.Random()  # noqa: S311 - pacing is not a security decision


def _pick(rng: random.Random | None) -> random.Random:
    return rng if rng is not None else _DEFAULT_RNG


def sample_gap_seconds(rng: random.Random | None = None) -> int:
    """One inter-action gap, in seconds.

    Median comes from settings; the spread (sigma) is chosen so the bulk of
    gaps land between roughly a third and three times the median, with a long
    thin tail — then clamped to the configured floor and ceiling.
    """
    rng = _pick(rng)
    median = settings.safety_median_action_gap_seconds
    sigma = 0.85  # in log space

    gap = rng.lognormvariate(math.log(median), sigma)
    return int(
        min(
            max(gap, settings.safety_min_action_gap_seconds),
            settings.safety_max_action_gap_seconds,
        )
    )


def next_allowed_at(now: datetime | None = None, rng: random.Random | None = None) -> datetime:
    """When this account may act again after completing an action."""
    now = now or datetime.now(UTC)
    return now + timedelta(seconds=sample_gap_seconds(rng))


def _combine(day: date, at: time, tzinfo: object) -> datetime:
    return datetime.combine(day, at).replace(tzinfo=tzinfo)  # type: ignore[arg-type]


def schedule_within_working_hours(
    account: LinkedInAccount,
    earliest: datetime,
    *,
    rng: random.Random | None = None,
    max_days_ahead: int = 14,
) -> datetime:
    """Moves `earliest` to the next moment the account is allowed to act.

    Returns a jittered time inside the working window rather than the window's
    opening second — a burst of accounts all firing at exactly 09:00:00 is a
    pattern, and it is the pattern a naive scheduler creates.
    """
    rng = _pick(rng)
    zone = caps_mod.zone_for(account)
    resolved = caps_mod.resolve(account, now=earliest)
    start, end = resolved.working_hours

    local = earliest.astimezone(zone)

    for offset in range(max_days_ahead + 1):
        day = (local + timedelta(days=offset)).date()
        window_start = _combine(day, start, zone)
        window_end = _combine(day, end, zone)

        if resolved.weekdays_only and day.weekday() >= 5:
            continue

        candidate_floor = max(window_start, local if offset == 0 else window_start)
        if candidate_floor >= window_end:
            continue  # today's window has already closed

        span = int((window_end - candidate_floor).total_seconds())
        if span <= 0:
            continue

        # Bias toward the earlier part of the remaining window so a queue does
        # not silently drift to the end of the day, but keep it irregular.
        jitter = int(rng.triangular(0, span, span * 0.25))
        return (candidate_floor + timedelta(seconds=jitter)).astimezone(UTC)

    # No window found within the horizon (a misconfigured account). Fall back to
    # the floor rather than scheduling nothing at all.
    return earliest + timedelta(days=1)


def spread_start_times(
    count: int, window_seconds: int, rng: random.Random | None = None
) -> list[int]:
    """Offsets for N accounts so a Beat sweep does not fire them simultaneously."""
    rng = _pick(rng)
    if count <= 0:
        return []
    return sorted(rng.randint(0, max(window_seconds, 1)) for _ in range(count))
