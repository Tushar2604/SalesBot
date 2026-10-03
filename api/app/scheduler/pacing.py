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

    Median comes from settings; drawn from a log-normal truncated to the
    configured floor and ceiling. Out-of-range draws are redrawn rather than
    clamped: with a narrow window (2-10 min) clamping would put a third of all
    gaps at exactly the floor or the ceiling, and a repeated identical gap is
    as much a machine signature as a flat histogram.
    """
    rng = _pick(rng)
    low = settings.safety_min_action_gap_seconds
    high = max(low, settings.safety_max_action_gap_seconds)
    median = min(max(settings.safety_median_action_gap_seconds, low), high)
    sigma = 0.7  # in log space

    for _ in range(20):
        gap = rng.lognormvariate(math.log(median), sigma)
        if low <= gap <= high:
            return int(gap)
    return int(rng.uniform(low, high))


def schedule_soon(
    account: LinkedInAccount, now: datetime, *, rng: random.Random | None = None
) -> datetime:
    """A near-term moment for a task that is due now.

    Inside working hours: a few seconds to a minute and a half from now — the
    dispatcher's per-account gap is what actually spaces actions out, so
    spreading a task across the whole day on top of it only made a freshly
    launched campaign sit idle for hours. Outside working hours: a jittered
    moment in the next window, as before.
    """
    rng = _pick(rng)
    if caps_mod.within_working_hours(account, now=now)[0]:
        return now + timedelta(seconds=rng.randint(5, 90))
    return schedule_within_working_hours(account, now, rng=rng)


def pipeline_start_offsets(count: int, rng: random.Random | None = None) -> list[timedelta]:
    """When each of `count` leads should enter a campaign, relative to launch.

    The first starts at once; each next one a fresh random gap later, so a
    launch works down the list one person at a time (view A, a few minutes
    later view B, then invite A...) instead of queueing everyone at once.
    """
    rng = _pick(rng)
    offsets: list[timedelta] = []
    total = 0
    for index in range(count):
        if index:
            total += sample_gap_seconds(rng)
        offsets.append(timedelta(seconds=total))
    return offsets


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
