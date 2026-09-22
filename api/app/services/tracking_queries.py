"""Read side of campaign tracking: the funnel, the per-lead table, the history.

Everything is derived from `campaign_leads` and `campaign_lead_events`, so it
works the same for a campaign that ran last month as for one started a minute ago.
"""

from __future__ import annotations

import csv
import io
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.campaigns import (
    Campaign,
    CampaignLead,
    CampaignLeadEvent,
    ConnectionState,
    EventType,
)
from app.models.leads import Lead
from app.services import tracking

# Order the funnel is shown in.
FUNNEL_ORDER = tracking.STAGES


async def summary(db: AsyncSession, campaign: Campaign) -> dict[str, Any]:
    cl = CampaignLead
    stage = tracking.stage_expression()

    rows = (
        await db.execute(
            select(stage.label("stage"), func.count())
            .where(cl.campaign_id == campaign.id)
            .group_by("stage")
        )
    ).all()
    by_stage = {str(name): int(count) for name, count in rows}
    total = sum(by_stage.values())

    ever = (
        await db.execute(
            select(
                func.count(cl.viewed_at),
                func.count(cl.invite_sent_at),
                func.count(cl.accepted_at),
                func.count(cl.replied_at),
            ).where(cl.campaign_id == campaign.id)
        )
    ).one()
    viewed, invited, connected, replied = (int(v) for v in ever)

    messaged = int(
        await db.scalar(
            select(func.count(func.distinct(CampaignLeadEvent.campaign_lead_id))).where(
                CampaignLeadEvent.campaign_id == campaign.id,
                CampaignLeadEvent.event_type == EventType.MESSAGE_SENT.value,
            )
        )
        or 0
    )

    pending_where = and_(
        cl.campaign_id == campaign.id, cl.connection_state == ConnectionState.PENDING.value
    )
    oldest_pending, next_check = (
        await db.execute(
            select(func.min(cl.invite_sent_at), func.min(cl.next_check_at)).where(pending_where)
        )
    ).one()

    avg_seconds = await db.scalar(
        select(func.avg(func.extract("epoch", cl.accepted_at - cl.invite_sent_at))).where(
            cl.campaign_id == campaign.id,
            cl.accepted_at.isnot(None),
            cl.invite_sent_at.isnot(None),
        )
    )

    answered = by_stage.get("connected", 0) + by_stage.get("replied", 0)
    return {
        "campaign_id": campaign.id,
        "campaign_name": campaign.name,
        "campaign_status": campaign.status.value,
        "total": total,
        "stages": [
            {"stage": s, "label": tracking.STAGE_LABELS[s], "count": by_stage.get(s, 0)}
            for s in FUNNEL_ORDER
        ],
        "viewed": viewed,
        "invited": invited,
        "connected": connected,
        "messaged": messaged,
        "replied": replied,
        "acceptance_rate": (connected / invited) if invited else None,
        "still_waiting": by_stage.get("invite_pending", 0),
        "not_accepted": by_stage.get("not_accepted", 0),
        "expired": by_stage.get("expired", 0),
        "answered": answered,
        "oldest_pending_days": tracking.days_between(oldest_pending),
        "avg_days_to_accept": round(float(avg_seconds) / 86400, 1) if avg_seconds else None,
        "next_check_at": next_check,
        "tracking_window_days": tracking.tracking_window().days,
    }


async def lead_page(
    db: AsyncSession,
    campaign: Campaign,
    *,
    stage: str | None,
    search: str,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    cl = CampaignLead
    stage_col = tracking.stage_expression()

    conditions = [cl.campaign_id == campaign.id]
    if stage:
        conditions.append(stage_col == stage)
    needle = search.strip()
    if needle:
        like = f"%{needle}%"
        conditions.append(
            or_(
                Lead.public_id.ilike(like),
                Lead.first_name.ilike(like),
                Lead.last_name.ilike(like),
                Lead.company.ilike(like),
            )
        )

    base = (
        select(cl, Lead, stage_col.label("stage"))
        .join(Lead, Lead.id == cl.lead_id)
        .where(*conditions)
    )
    total = int(
        await db.scalar(
            select(func.count())
            .select_from(cl)
            .join(Lead, Lead.id == cl.lead_id)
            .where(*conditions)
        )
        or 0
    )
    activity = func.coalesce(
        cl.connection_resolved_at, cl.invite_sent_at, cl.viewed_at, cl.created_at
    )
    rows = (await db.execute(base.order_by(activity.desc()).limit(limit).offset(offset))).all()

    ids = [enrollment.id for enrollment, _, _ in rows]
    latest: dict[uuid.UUID, CampaignLeadEvent] = {}
    if ids:
        events = (
            await db.execute(
                select(CampaignLeadEvent)
                .where(CampaignLeadEvent.campaign_lead_id.in_(ids))
                .distinct(CampaignLeadEvent.campaign_lead_id)
                .order_by(CampaignLeadEvent.campaign_lead_id, CampaignLeadEvent.occurred_at.desc())
            )
        ).scalars()
        latest = {e.campaign_lead_id: e for e in events}

    now = datetime.now(UTC)
    items: list[dict[str, Any]] = []
    for enrollment, lead, stage_name in rows:
        last = latest.get(enrollment.id)
        pending = enrollment.connection_state == ConnectionState.PENDING.value
        items.append(
            {
                "id": enrollment.id,
                "lead_id": lead.id,
                "lead_name": lead.full_name or lead.public_id,
                "lead_public_id": lead.public_id,
                "lead_company": lead.company,
                "lead_title": lead.title,
                "stage": stage_name,
                "stage_label": tracking.STAGE_LABELS[stage_name],
                "reason": enrollment.stopped_reason
                if stage_name in ("stopped", "skipped")
                else enrollment.last_error
                if stage_name == "failed"
                else "",
                "viewed_at": enrollment.viewed_at,
                "invite_sent_at": enrollment.invite_sent_at,
                "days_waiting": tracking.days_between(enrollment.invite_sent_at, now)
                if pending
                else None,
                "accepted_at": enrollment.accepted_at,
                "resolved_at": enrollment.connection_resolved_at,
                "last_checked_at": enrollment.last_checked_at,
                "next_check_at": enrollment.next_check_at if pending else None,
                "check_count": enrollment.check_count,
                "replied_at": enrollment.replied_at,
                "last_event_type": last.event_type if last else "",
                "last_event_detail": last.detail if last else "",
                "last_event_at": last.occurred_at if last else None,
            }
        )
    return items, total


async def timeline(
    db: AsyncSession, campaign: Campaign, enrollment_id: uuid.UUID
) -> list[CampaignLeadEvent] | None:
    exists = await db.scalar(
        select(CampaignLead.id).where(
            CampaignLead.id == enrollment_id, CampaignLead.campaign_id == campaign.id
        )
    )
    if exists is None:
        return None
    return list(
        (
            await db.execute(
                select(CampaignLeadEvent)
                .where(CampaignLeadEvent.campaign_lead_id == enrollment_id)
                .order_by(CampaignLeadEvent.occurred_at.desc(), CampaignLeadEvent.id)
            )
        )
        .scalars()
        .all()
    )


async def export_csv(db: AsyncSession, campaign: Campaign) -> str:
    """Every lead with its stage and milestone dates, for a spreadsheet."""
    items, _ = await lead_page(db, campaign, stage=None, search="", limit=100_000, offset=0)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "name",
            "linkedin",
            "company",
            "title",
            "stage",
            "profile_viewed",
            "invite_sent",
            "days_waiting",
            "connected",
            "resolved",
            "last_checked",
            "checks",
            "replied",
            "reason",
        ]
    )
    for item in items:
        writer.writerow(
            [
                item["lead_name"],
                f"https://www.linkedin.com/in/{item['lead_public_id']}",
                item["lead_company"],
                item["lead_title"],
                item["stage_label"],
                *(item[k].isoformat() if item[k] else "" for k in ("viewed_at", "invite_sent_at")),
                item["days_waiting"] if item["days_waiting"] is not None else "",
                *(
                    item[k].isoformat() if item[k] else ""
                    for k in ("accepted_at", "resolved_at", "last_checked_at")
                ),
                item["check_count"],
                item["replied_at"].isoformat() if item["replied_at"] else "",
                item["reason"],
            ]
        )
    return out.getvalue()
