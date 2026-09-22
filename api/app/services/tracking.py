"""Per-lead outreach tracking: the event history and the check schedule.

Every notable thing that happens to a lead in a campaign is appended to
`campaign_lead_events`; the latest connection observation is kept on the
enrollment itself. Nothing here talks to LinkedIn.

LinkedIn never says "declined". What we can observe on a profile is whether the
invite is still pending, whether the person is now a connection, or neither.
`NOT_ACCEPTED` is that third case, and the UI says so plainly rather than
pretending to know why.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import Case, case
from sqlalchemy.orm import object_session

from app.config import settings
from app.models.campaigns import (
    CampaignLead,
    CampaignLeadEvent,
    ConnectionState,
    EnrollmentState,
    EventType,
)

# Funnel stages, one per lead. Ordered by how far along the person got.
STAGES: tuple[str, ...] = (
    "queued",
    "profile_viewed",
    "invite_pending",
    "connected",
    "replied",
    "not_accepted",
    "expired",
    "stopped",
    "failed",
    "skipped",
)

STAGE_LABELS: dict[str, str] = {
    "queued": "Queued",
    "profile_viewed": "Profile viewed",
    "invite_pending": "Invite pending",
    "connected": "Connected",
    "replied": "Replied",
    "not_accepted": "Not accepted",
    "expired": "No response",
    "stopped": "Stopped",
    "failed": "Failed",
    "skipped": "Skipped",
}


def log_event(
    enrollment: CampaignLead,
    event_type: EventType,
    detail: str = "",
    *,
    at: datetime | None = None,
    meta: dict[str, Any] | None = None,
) -> CampaignLeadEvent | None:
    """Appends one event to the enrollment's history, in the enrollment's own session."""
    session = object_session(enrollment)
    if session is None:
        return None
    event = CampaignLeadEvent(
        workspace_id=enrollment.workspace_id,
        campaign_id=enrollment.campaign_id,
        campaign_lead_id=enrollment.id,
        event_type=event_type.value,
        detail=detail[:300],
        meta=meta or {},
        occurred_at=at or datetime.now(UTC),
    )
    session.add(event)
    return event


def tracking_window() -> timedelta:
    return timedelta(days=settings.linkedin_invite_tracking_days)


def first_check_at(invited_at: datetime) -> datetime:
    """The first look at a fresh invite: not before it has had time to be answered."""
    return invited_at + timedelta(minutes=settings.linkedin_acceptance_min_age_minutes)


def next_check_delay(invite_age: timedelta) -> timedelta:
    """How long to wait before looking again.

    Each look is a real profile page load, so it backs off as the odds of a
    change fall: people answer quickly or not at all.
    """
    if invite_age < timedelta(days=1):
        return timedelta(hours=2)
    if invite_age < timedelta(days=3):
        return timedelta(hours=6)
    return timedelta(hours=24)


def days_between(start: datetime | None, end: datetime | None = None) -> int | None:
    if start is None:
        return None
    return max(0, ((end or datetime.now(UTC)) - start).days)


def stage_expression() -> Case[str]:
    """SQL for a lead's funnel stage. Order matters: the first match wins."""
    cl = CampaignLead
    return case(
        (cl.replied_at.isnot(None), "replied"),
        (cl.connection_state == ConnectionState.CONNECTED.value, "connected"),
        (cl.connection_state == ConnectionState.NOT_ACCEPTED.value, "not_accepted"),
        (cl.connection_state == ConnectionState.EXPIRED.value, "expired"),
        (cl.connection_state == ConnectionState.PENDING.value, "invite_pending"),
        (cl.state == EnrollmentState.FAILED, "failed"),
        (cl.state == EnrollmentState.SKIPPED, "skipped"),
        (cl.state == EnrollmentState.STOPPED, "stopped"),
        (cl.viewed_at.isnot(None), "profile_viewed"),
        else_="queued",
    )
