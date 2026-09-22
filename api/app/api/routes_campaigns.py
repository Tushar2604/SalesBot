"""Campaign endpoints: build, enroll, launch, observe.

Nothing here performs an action. Launching a campaign only changes a status;
the dispatcher notices on its next tick and decides for itself whether an
action may happen. That separation is why a launch can never bypass a quota.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.db import get_db
from app.deps import Workspace_
from app.linkedin import caps as caps_mod
from app.linkedin import health
from app.models.campaigns import (
    ActionTask,
    Campaign,
    CampaignLead,
    CampaignStatus,
    StepType,
)
from app.models.leads import Lead
from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus
from app.models.tenancy import WorkspaceRole
from app.scheduler import quota, templating
from app.schemas.outreach import (
    ActionTaskResponse,
    CampaignCreateRequest,
    CampaignResponse,
    CampaignStatsResponse,
    CampaignUpdateRequest,
    EnrollmentPage,
    EnrollmentResponse,
    EnrollReportResponse,
    EnrollRequest,
    LeadEventResponse,
    QuotaStatusResponse,
    StatusChangeRequest,
    StepRequest,
    StepResponse,
    TemplatePreviewRequest,
    TemplatePreviewResponse,
    TrackingLeadPage,
    TrackingLeadResponse,
    TrackingSummaryResponse,
)
from app.services import campaign_service, tracking, tracking_queries

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["campaigns"])


def _specs(steps: list[StepRequest]) -> list[campaign_service.StepSpec]:
    return [
        campaign_service.StepSpec(
            step_type=step.step_type,
            delay_hours=step.delay_hours,
            only_if=step.only_if,
            on_condition_fail=step.on_condition_fail,
            template=step.template,
            timing=step.timing,
            delay_minutes=step.delay_minutes,
            send_at=step.send_at,
        )
        for step in steps
    ]


async def _launch_blockers(
    db: AsyncSession, campaign: Campaign
) -> tuple[list[str], LinkedInAccount | None]:
    """Everything standing between this campaign and sending, in plain words."""
    blockers: list[str] = []
    account = await db.get(LinkedInAccount, campaign.linkedin_account_id)

    if not campaign.steps:
        blockers.append("Add at least one step to the sequence.")

    enrolled = await db.scalar(
        select(func.count())
        .select_from(CampaignLead)
        .where(CampaignLead.campaign_id == campaign.id)
    )
    if not enrolled:
        blockers.append("Enroll some leads.")

    if account is None:
        blockers.append("The LinkedIn account for this campaign no longer exists.")
        return blockers, None

    if account.status is not LinkedInAccountStatus.ACTIVE:
        blockers.append(
            f"The LinkedIn account is {account.status.value.replace('_', ' ')} — "
            "reconnect it on the accounts page."
        )
    else:
        allowed, reason = health.can_dispatch(account)
        if not allowed:
            blockers.append(f"The account cannot act right now: {reason}")

    return blockers, account


async def _to_response(db: AsyncSession, campaign: Campaign) -> CampaignResponse:
    stats = await campaign_service.campaign_stats(db, campaign)
    blockers, account = await _launch_blockers(db, campaign)

    return CampaignResponse(
        id=campaign.id,
        name=campaign.name,
        status=campaign.status,
        stop_on_reply=campaign.stop_on_reply,
        linkedin_account_id=campaign.linkedin_account_id,
        linkedin_account_label=(account.label if account else "(deleted account)"),
        steps=[StepResponse.model_validate(step) for step in campaign.steps],
        stats=CampaignStatsResponse(
            enrolled=stats.enrolled,
            pending=stats.pending,
            running=stats.running,
            completed=stats.completed,
            replied=stats.replied,
            stopped=stats.stopped,
            skipped=stats.skipped,
            failed=stats.failed,
            invites_sent=stats.invites_sent,
            accepted=stats.accepted,
            messages_sent=stats.messages_sent,
            views=stats.views,
            tasks_pending=stats.tasks_pending,
            tasks_failed=stats.tasks_failed,
            acceptance_rate=stats.acceptance_rate,
            reply_rate=stats.reply_rate,
        ),
        started_at=campaign.started_at,
        completed_at=campaign.completed_at,
        created_at=campaign.created_at,
        launch_blockers=blockers,
    )


@router.get("/campaigns", response_model=list[CampaignResponse])
async def list_campaigns(
    ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[CampaignResponse]:
    campaigns = await campaign_service.list_campaigns(db, ctx.workspace_id)
    return [await _to_response(db, campaign) for campaign in campaigns]


@router.post("/campaigns", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignCreateRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CampaignResponse:
    ctx.require_role(WorkspaceRole.MEMBER)
    campaign = await campaign_service.create_campaign(
        db,
        ctx,
        name=payload.name,
        linkedin_account_id=payload.linkedin_account_id,
        steps=_specs(payload.steps),
        stop_on_reply=payload.stop_on_reply,
    )
    return await _to_response(db, campaign)


@router.get("/campaigns/{campaign_id}", response_model=CampaignResponse)
async def get_campaign(
    campaign_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> CampaignResponse:
    campaign = await campaign_service.get_campaign(db, ctx.workspace_id, campaign_id)
    return await _to_response(db, campaign)


@router.patch("/campaigns/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: uuid.UUID,
    payload: CampaignUpdateRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CampaignResponse:
    ctx.require_role(WorkspaceRole.MEMBER)
    campaign = await campaign_service.get_campaign(db, ctx.workspace_id, campaign_id)
    if payload.name is not None:
        campaign.name = payload.name.strip()
    if payload.stop_on_reply is not None:
        campaign.stop_on_reply = payload.stop_on_reply
    return await _to_response(db, campaign)


@router.put("/campaigns/{campaign_id}/steps", response_model=CampaignResponse)
async def replace_steps(
    campaign_id: uuid.UUID,
    payload: list[StepRequest],
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CampaignResponse:
    ctx.require_role(WorkspaceRole.MEMBER)
    campaign = await campaign_service.get_campaign(db, ctx.workspace_id, campaign_id)
    campaign = await campaign_service.replace_steps(db, ctx, campaign, _specs(payload))
    return await _to_response(db, campaign)


@router.post("/campaigns/{campaign_id}/enroll", response_model=EnrollReportResponse)
async def enroll(
    campaign_id: uuid.UUID,
    payload: EnrollRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EnrollReportResponse:
    ctx.require_role(WorkspaceRole.MEMBER)
    campaign = await campaign_service.get_campaign(db, ctx.workspace_id, campaign_id)
    report = await campaign_service.enroll_leads(
        db,
        ctx,
        campaign,
        lead_ids=payload.lead_ids or None,
        list_id=payload.list_id,
    )
    return EnrollReportResponse(
        enrolled=report.enrolled,
        skipped_duplicate=report.skipped_duplicate,
        skipped_blocked=report.skipped_blocked,
        skipped_already_enrolled=report.skipped_already_enrolled,
        skipped_no_profile=report.skipped_no_profile,
        total_skipped=report.total_skipped,
    )


@router.post("/campaigns/{campaign_id}/status", response_model=CampaignResponse)
async def change_status(
    campaign_id: uuid.UUID,
    payload: StatusChangeRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CampaignResponse:
    """Launch, pause, complete, or archive."""
    ctx.require_role(WorkspaceRole.MEMBER)
    campaign = await campaign_service.get_campaign(db, ctx.workspace_id, campaign_id)
    campaign = await campaign_service.set_status(db, ctx, campaign, CampaignStatus(payload.status))
    return await _to_response(db, campaign)


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    campaign_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> None:
    ctx.require_role(WorkspaceRole.ADMIN)
    campaign = await campaign_service.get_campaign(db, ctx.workspace_id, campaign_id)
    await db.delete(campaign)


@router.get("/campaigns/{campaign_id}/enrollments", response_model=EnrollmentPage)
async def list_enrollments(
    campaign_id: uuid.UUID,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EnrollmentPage:
    campaign = await campaign_service.get_campaign(db, ctx.workspace_id, campaign_id)

    total = int(
        await db.scalar(
            select(func.count())
            .select_from(CampaignLead)
            .where(CampaignLead.campaign_id == campaign.id)
        )
        or 0
    )
    rows = (
        await db.execute(
            select(CampaignLead, Lead)
            .join(Lead, Lead.id == CampaignLead.lead_id)
            .where(CampaignLead.campaign_id == campaign.id)
            .order_by(CampaignLead.created_at)
            .limit(limit)
            .offset(offset)
        )
    ).all()

    return EnrollmentPage(
        items=[
            EnrollmentResponse(
                id=enrollment.id,
                lead_id=lead.id,
                lead_name=lead.full_name or lead.public_id,
                lead_public_id=lead.public_id,
                lead_company=lead.company,
                state=enrollment.state,
                current_step_index=enrollment.current_step_index,
                variant=enrollment.variant,
                next_run_at=enrollment.next_run_at,
                invite_sent_at=enrollment.invite_sent_at,
                accepted_at=enrollment.accepted_at,
                replied_at=enrollment.replied_at,
                last_error=enrollment.last_error,
                stopped_reason=enrollment.stopped_reason,
            )
            for enrollment, lead in rows
        ],
        total=total,
    )


@router.get("/campaigns/{campaign_id}/activity", response_model=list[ActionTaskResponse])
async def list_activity(
    campaign_id: uuid.UUID,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ActionTaskResponse]:
    """What the engine actually did, most recent first."""
    campaign = await campaign_service.get_campaign(db, ctx.workspace_id, campaign_id)

    rows = (
        await db.execute(
            select(ActionTask, Lead)
            .join(CampaignLead, CampaignLead.id == ActionTask.campaign_lead_id)
            .join(Lead, Lead.id == CampaignLead.lead_id)
            .where(CampaignLead.campaign_id == campaign.id)
            .order_by(ActionTask.created_at.desc())
            .limit(limit)
        )
    ).all()

    return [
        ActionTaskResponse(
            id=task.id,
            action_type=task.action_type,
            status=task.status.value,
            scheduled_at=task.scheduled_at,
            dispatched_at=task.dispatched_at,
            finished_at=task.finished_at,
            attempts=task.attempts,
            error_class=task.error_class,
            error_detail=task.error_detail,
            lead_public_id=lead.public_id,
        )
        for task, lead in rows
    ]


@router.get("/campaigns/{campaign_id}/tracking", response_model=TrackingSummaryResponse)
async def tracking_summary(
    campaign_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> TrackingSummaryResponse:
    """The funnel: how many leads are at each stage right now."""
    campaign = await campaign_service.get_campaign(db, ctx.workspace_id, campaign_id)
    return TrackingSummaryResponse(**await tracking_queries.summary(db, campaign))


@router.get("/campaigns/{campaign_id}/tracking/leads", response_model=TrackingLeadPage)
async def tracking_leads(
    campaign_id: uuid.UUID,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
    stage: Annotated[str | None, Query(description="One of the funnel stages")] = None,
    search: Annotated[str, Query(max_length=100)] = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TrackingLeadPage:
    """Every lead with its current stage, filterable by stage or name."""
    if stage is not None and stage not in tracking.STAGES:
        raise NotFoundError(f"unknown stage {stage!r}")
    campaign = await campaign_service.get_campaign(db, ctx.workspace_id, campaign_id)
    items, total = await tracking_queries.lead_page(
        db, campaign, stage=stage, search=search, limit=limit, offset=offset
    )
    return TrackingLeadPage(items=[TrackingLeadResponse(**i) for i in items], total=total)


@router.get(
    "/campaigns/{campaign_id}/enrollments/{enrollment_id}/events",
    response_model=list[LeadEventResponse],
)
async def lead_events(
    campaign_id: uuid.UUID,
    enrollment_id: uuid.UUID,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[LeadEventResponse]:
    """One lead's full history in this campaign, newest first."""
    campaign = await campaign_service.get_campaign(db, ctx.workspace_id, campaign_id)
    events = await tracking_queries.timeline(db, campaign, enrollment_id)
    if events is None:
        raise NotFoundError("that lead is not in this campaign")
    return [LeadEventResponse.model_validate(e) for e in events]


@router.get("/campaigns/{campaign_id}/tracking/export.csv")
async def tracking_export(
    campaign_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> Response:
    campaign = await campaign_service.get_campaign(db, ctx.workspace_id, campaign_id)
    body = await tracking_queries.export_csv(db, campaign)
    return Response(
        content=body,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="campaign-tracking.csv"'},
    )


@router.post("/campaigns/preview-template", response_model=TemplatePreviewResponse)
async def preview_template(
    payload: TemplatePreviewRequest, ctx: Workspace_
) -> TemplatePreviewResponse:
    """Renders a template with sample data, and names its unsafe variables."""
    _ = ctx
    rendered = templating.preview(payload.template)
    return TemplatePreviewResponse(
        rendered=rendered,
        variables=sorted(templating.variables_used(payload.template)),
        variables_without_fallback=sorted(templating.variables_without_fallback(payload.template)),
        length=len(rendered),
        exceeds_invite_limit=len(rendered) > templating.MAX_INVITE_NOTE_CHARS,
    )


@router.get("/quota-status", response_model=list[QuotaStatusResponse])
async def quota_status(
    ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[QuotaStatusResponse]:
    """Live view of what the safety engine permits per account.

    The point is that a user who sees "0 of 3 invites used, next at 14:20" never
    has to wonder whether the system is broken or just being careful.
    """
    accounts = (
        (
            await db.execute(
                select(LinkedInAccount)
                .where(LinkedInAccount.workspace_id == ctx.workspace_id)
                .order_by(LinkedInAccount.created_at)
            )
        )
        .scalars()
        .all()
    )

    result: list[QuotaStatusResponse] = []
    for account in accounts:
        resolved = caps_mod.resolve(account)
        in_hours, hours_detail = caps_mod.within_working_hours(account)
        allowed, reason = health.can_dispatch(account)
        blocked = ""
        if ctx.workspace.outreach_paused:
            blocked = "workspace kill switch is on"
        elif not allowed:
            blocked = reason
        elif not in_hours:
            blocked = hours_detail

        # The async session cannot run the sync quota helpers, so the ledger is
        # read directly here.
        invites_today = await _ledger(db, account, StepType.INVITE)
        invites_week = await _ledger_week(db, account, StepType.INVITE)
        messages_today = await _ledger(db, account, StepType.MESSAGE)
        views_today = await _ledger(db, account, StepType.VIEW_PROFILE)

        result.append(
            QuotaStatusResponse(
                linkedin_account_id=account.id,
                label=account.label,
                status=account.status.value,
                within_working_hours=in_hours,
                working_hours_detail=hours_detail,
                next_allowed_at=account.next_allowed_at,
                blocked_reason=blocked,
                invites_used_today=invites_today,
                invites_limit_today=resolved.daily_invites,
                invites_used_this_week=invites_week,
                invites_limit_this_week=resolved.weekly_invites,
                invite_limit_reason=resolved.invite_limit_reason,
                messages_used_today=messages_today,
                messages_limit_today=resolved.daily_messages,
                views_used_today=views_today,
                views_limit_today=resolved.daily_views,
            )
        )
    return result


async def _ledger(db: AsyncSession, account: LinkedInAccount, action: StepType) -> int:
    from app.models.campaigns import DailyQuotaLedger

    value = await db.scalar(
        select(DailyQuotaLedger.used).where(
            DailyQuotaLedger.linkedin_account_id == account.id,
            DailyQuotaLedger.day == quota.local_day(account),
            DailyQuotaLedger.action_type == action,
        )
    )
    return int(value or 0)


async def _ledger_week(db: AsyncSession, account: LinkedInAccount, action: StepType) -> int:
    from datetime import timedelta

    from app.models.campaigns import DailyQuotaLedger

    today = quota.local_day(account)
    value = await db.scalar(
        select(func.coalesce(func.sum(DailyQuotaLedger.used), 0)).where(
            DailyQuotaLedger.linkedin_account_id == account.id,
            DailyQuotaLedger.action_type == action,
            DailyQuotaLedger.day >= today - timedelta(days=6),
            DailyQuotaLedger.day <= today,
        )
    )
    return int(value or 0)
