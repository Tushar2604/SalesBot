"""Workspace analytics: the Dashboard's "Your Analytics" panel.

Every number here comes from a real table — `DailyQuotaLedger` (actions we
actually dispatched), `CampaignLead` (accept/reply milestones), `ActionTask`
(failures) — never a synthesized or placeholder value. There is deliberately
no row for a channel this product does not support yet (voice/video notes,
InMail, meetings): a zeroed-out row for a feature that does not exist would
misrepresent the product, not just be empty.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaigns import ActionTask, Campaign, CampaignLead, DailyQuotaLedger, StepType, TaskStatus
from app.models.linkedin import LinkedInAccount

SERIES = ("prospects_reached", "connection_requests", "follow_ups", "connected", "replied", "failed")

SERIES_LABELS = {
    "prospects_reached": "Prospects Reached",
    "connection_requests": "Connection Requests",
    "follow_ups": "Follow-ups",
    "connected": "Connected",
    "replied": "Replied",
    "failed": "Failed Actions",
}


@dataclass(slots=True)
class DailySeries:
    key: str
    label: str
    counts: list[int]


@dataclass(slots=True)
class AnalyticsOverview:
    days: list[date]
    series: list[DailySeries]
    total_campaigns: int
    running_campaigns: int
    prospects_reached: int
    total_connected: int
    total_replies: int


def _day_range(days: int) -> list[date]:
    today = datetime.now(UTC).date()
    return [today - timedelta(days=offset) for offset in range(days - 1, -1, -1)]


async def _ledger_counts(
    db: AsyncSession, workspace_id: uuid.UUID, start: date, action_type: StepType
) -> dict[date, int]:
    rows = (
        await db.execute(
            select(DailyQuotaLedger.day, func.sum(DailyQuotaLedger.used))
            .join(LinkedInAccount, LinkedInAccount.id == DailyQuotaLedger.linkedin_account_id)
            .where(
                LinkedInAccount.workspace_id == workspace_id,
                DailyQuotaLedger.action_type == action_type,
                DailyQuotaLedger.day >= start,
            )
            .group_by(DailyQuotaLedger.day)
        )
    ).all()
    return {row[0]: int(row[1] or 0) for row in rows}


async def _milestone_counts(
    db: AsyncSession, workspace_id: uuid.UUID, start: datetime, column
) -> dict[date, int]:
    rows = (
        await db.execute(
            select(cast(column, Date), func.count())
            .where(
                CampaignLead.workspace_id == workspace_id,
                column.isnot(None),
                column >= start,
            )
            .group_by(cast(column, Date))
        )
    ).all()
    return {row[0]: int(row[1]) for row in rows}


async def _failed_counts(db: AsyncSession, workspace_id: uuid.UUID, start: datetime) -> dict[date, int]:
    rows = (
        await db.execute(
            select(cast(ActionTask.finished_at, Date), func.count())
            .where(
                ActionTask.workspace_id == workspace_id,
                ActionTask.status == TaskStatus.FAILED,
                ActionTask.finished_at.isnot(None),
                ActionTask.finished_at >= start,
            )
            .group_by(cast(ActionTask.finished_at, Date))
        )
    ).all()
    return {row[0]: int(row[1]) for row in rows}


async def overview(db: AsyncSession, workspace_id: uuid.UUID, days: int = 7) -> AnalyticsOverview:
    return await _build(db, workspace_id, _day_range(days))


def _combine_utc(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


async def _build(db: AsyncSession, workspace_id: uuid.UUID, day_list: list[date]) -> AnalyticsOverview:
    start_day = day_list[0]
    start_dt = _combine_utc(start_day)

    reached_by_day = await _ledger_counts(db, workspace_id, start_day, StepType.VIEW_PROFILE)
    invites_by_day = await _ledger_counts(db, workspace_id, start_day, StepType.INVITE)
    messages_by_day = await _ledger_counts(db, workspace_id, start_day, StepType.MESSAGE)
    connected_by_day = await _milestone_counts(db, workspace_id, start_dt, CampaignLead.accepted_at)
    replied_by_day = await _milestone_counts(db, workspace_id, start_dt, CampaignLead.replied_at)
    failed_by_day = await _failed_counts(db, workspace_id, start_dt)

    series = [
        DailySeries("prospects_reached", SERIES_LABELS["prospects_reached"], [reached_by_day.get(d, 0) for d in day_list]),
        DailySeries("connection_requests", SERIES_LABELS["connection_requests"], [invites_by_day.get(d, 0) for d in day_list]),
        DailySeries("follow_ups", SERIES_LABELS["follow_ups"], [messages_by_day.get(d, 0) for d in day_list]),
        DailySeries("connected", SERIES_LABELS["connected"], [connected_by_day.get(d, 0) for d in day_list]),
        DailySeries("replied", SERIES_LABELS["replied"], [replied_by_day.get(d, 0) for d in day_list]),
        DailySeries("failed", SERIES_LABELS["failed"], [failed_by_day.get(d, 0) for d in day_list]),
    ]

    total_campaigns = (
        await db.scalar(select(func.count()).select_from(Campaign).where(Campaign.workspace_id == workspace_id))
    ) or 0
    running_campaigns = (
        await db.scalar(
            select(func.count())
            .select_from(Campaign)
            .where(Campaign.workspace_id == workspace_id, Campaign.status == "running")
        )
    ) or 0

    return AnalyticsOverview(
        days=day_list,
        series=series,
        total_campaigns=total_campaigns,
        running_campaigns=running_campaigns,
        prospects_reached=sum(reached_by_day.values()),
        total_connected=sum(connected_by_day.values()),
        total_replies=sum(replied_by_day.values()),
    )
