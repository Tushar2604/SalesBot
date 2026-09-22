"""Campaign creation, validation, enrollment, and stats.

Validation is strict on purpose. A campaign is a loaded gun pointed at a real
LinkedIn account: a sequence that messages before connecting, or whose template
references a field the leads do not have, fails at send time — by which point
the damage is a burnt prospect or a flagged account. Catching it at build time
is much cheaper.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.deps import WorkspaceContext
from app.models.campaigns import (
    ActionTask,
    Campaign,
    CampaignLead,
    CampaignStatus,
    CampaignStep,
    ConditionFailAction,
    EnrollmentState,
    EventType,
    StepCondition,
    StepType,
    TaskStatus,
)
from app.models.leads import ContactedLead, Lead
from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus
from app.scheduler import engine, templating
from app.services import audit, lead_service, tracking

# Steps that need a non-empty template.
NEEDS_TEMPLATE = {StepType.MESSAGE}
# Steps whose template is optional but length-capped.
OPTIONAL_TEMPLATE = {StepType.INVITE}


@dataclass(slots=True)
class StepSpec:
    """A step as the builder submits it, before it becomes a row."""

    step_type: StepType
    delay_hours: int = 0
    only_if: StepCondition = StepCondition.ALWAYS
    on_condition_fail: ConditionFailAction = ConditionFailAction.SKIP
    template: str = ""
    timing: str = "smart"
    delay_minutes: int | None = None
    send_at: datetime | None = None

    def config(self) -> dict[str, object]:
        """The timing settings as stored on the step row (defaults are omitted)."""
        out: dict[str, object] = {}
        if self.timing != "smart":
            out["timing"] = self.timing
        if self.delay_minutes is not None:
            out["delay_minutes"] = self.delay_minutes
        if self.send_at is not None:
            when = self.send_at if self.send_at.tzinfo else self.send_at.replace(tzinfo=UTC)
            out["send_at"] = when.astimezone(UTC).isoformat()
        return out


def _build_steps(specs: list[StepSpec]) -> list[CampaignStep]:
    """Turns specs into ordered step rows. `order_index` is the list position."""
    return [
        CampaignStep(
            order_index=index,
            step_type=spec.step_type,
            delay_hours=spec.delay_hours,
            only_if=spec.only_if,
            on_condition_fail=spec.on_condition_fail,
            template=spec.template,
            config=spec.config(),
        )
        for index, spec in enumerate(specs)
    ]


def validate_steps(specs: list[StepSpec]) -> list[str]:
    """Returns human-readable problems. Empty means the sequence is sound."""
    problems: list[str] = []

    if not specs:
        return ["a campaign needs at least one step"]

    for index, spec in enumerate(specs, start=1):
        label = f"Step {index} ({spec.step_type.value})"

        if spec.delay_hours < 0:
            problems.append(f"{label}: delay cannot be negative")
        if spec.timing == "at" and spec.send_at is None:
            problems.append(f"{label}: pick the date and time to send")
        if spec.timing == "delay" and spec.delay_minutes is None:
            problems.append(f"{label}: enter how long to wait")

        if spec.step_type in NEEDS_TEMPLATE and not spec.template.strip():
            problems.append(f"{label}: needs a message")

        if spec.step_type in NEEDS_TEMPLATE | OPTIONAL_TEMPLATE and spec.template:
            if spec.step_type is StepType.INVITE:
                rendered = templating.preview(spec.template)
                if len(rendered) > templating.MAX_INVITE_NOTE_CHARS:
                    problems.append(
                        f"{label}: the note renders to {len(rendered)} characters; "
                        f"LinkedIn allows {templating.MAX_INVITE_NOTE_CHARS}"
                    )
            try:
                templating.preview(spec.template)
            except Exception as exc:
                problems.append(f"{label}: template could not be rendered ({exc})")

    # Ordering sanity: messaging someone you have not connected with only works
    # for existing connections, so it is almost always a mistake in a sequence
    # that also sends an invite.
    types = [spec.step_type for spec in specs]
    if StepType.INVITE in types and StepType.MESSAGE in types:
        first_invite = types.index(StepType.INVITE)
        first_message = types.index(StepType.MESSAGE)
        if first_message < first_invite:
            problems.append(
                "Step order: a message before the connection request will fail unless "
                "you are already connected. Move the invite earlier."
            )

    # A message right after an invite, with no acceptance gate, will bounce for
    # everyone who has not accepted yet.
    for index, spec in enumerate(specs):
        if (
            spec.step_type is StepType.MESSAGE
            and index > 0
            and specs[index - 1].step_type is StepType.INVITE
            and spec.only_if not in (StepCondition.IF_ACCEPTED, StepCondition.IF_NOT_REPLIED)
        ):
            problems.append(
                f"Step {index + 1}: a message straight after an invite should be gated on "
                "'if_accepted', or it will be attempted on people who never connected"
            )

    return problems


async def create_campaign(
    db: AsyncSession,
    ctx: WorkspaceContext,
    *,
    name: str,
    linkedin_account_id: uuid.UUID,
    steps: list[StepSpec],
    stop_on_reply: bool = True,
) -> Campaign:
    account = (
        await db.execute(
            select(LinkedInAccount).where(
                LinkedInAccount.id == linkedin_account_id,
                LinkedInAccount.workspace_id == ctx.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise NotFoundError("LinkedIn account not found")

    problems = validate_steps(steps)
    if problems:
        raise ValidationFailedError("this sequence has problems", details={"problems": problems})

    campaign = Campaign(
        workspace_id=ctx.workspace_id,
        created_by_id=ctx.user.id,
        linkedin_account_id=account.id,
        name=name.strip(),
        status=CampaignStatus.DRAFT,
        stop_on_reply=stop_on_reply,
    )
    # Assigned through the relationship rather than inserted as separate rows:
    # that populates the collection in memory, so presenting this campaign does
    # not trigger a lazy load — which would be IO from sync code inside an
    # async handler.
    campaign.steps = _build_steps(steps)

    db.add(campaign)
    await db.flush()

    await audit.record(
        db,
        "campaign.created",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="campaign",
        target_id=campaign.id,
        metadata={"steps": [s.step_type.value for s in steps], "account_id": str(account.id)},
    )
    return campaign


async def replace_steps(
    db: AsyncSession, ctx: WorkspaceContext, campaign: Campaign, steps: list[StepSpec]
) -> Campaign:
    """Rewrites a sequence. Only allowed while nobody is mid-flight."""
    if campaign.status is CampaignStatus.RUNNING:
        raise ConflictError("pause the campaign before changing its sequence")

    problems = validate_steps(steps)
    if problems:
        raise ValidationFailedError("this sequence has problems", details={"problems": problems})

    # `delete-orphan` on the relationship removes the replaced rows, and
    # assigning the new collection keeps it loaded in memory for the response.
    campaign.steps = _build_steps(steps)
    await db.flush()

    await audit.record(
        db,
        "campaign.sequence_replaced",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="campaign",
        target_id=campaign.id,
        metadata={"steps": [spec.step_type.value for spec in steps]},
    )
    return campaign


async def get_campaign(
    db: AsyncSession, workspace_id: uuid.UUID, campaign_id: uuid.UUID
) -> Campaign:
    campaign = (
        await db.execute(
            select(Campaign).where(
                Campaign.id == campaign_id, Campaign.workspace_id == workspace_id
            )
        )
    ).scalar_one_or_none()
    if campaign is None:
        raise NotFoundError("campaign not found")
    return campaign


async def list_campaigns(db: AsyncSession, workspace_id: uuid.UUID) -> list[Campaign]:
    return list(
        (
            await db.execute(
                select(Campaign)
                .where(Campaign.workspace_id == workspace_id)
                .order_by(Campaign.created_at.desc())
            )
        )
        .scalars()
        .all()
    )


@dataclass(slots=True)
class EnrollReport:
    enrolled: int = 0
    skipped_duplicate: int = 0
    skipped_blocked: int = 0
    skipped_already_enrolled: int = 0
    skipped_no_profile: int = 0

    @property
    def total_skipped(self) -> int:
        return (
            self.skipped_duplicate
            + self.skipped_blocked
            + self.skipped_already_enrolled
            + self.skipped_no_profile
        )


async def enroll_leads(
    db: AsyncSession,
    ctx: WorkspaceContext,
    campaign: Campaign,
    *,
    lead_ids: list[uuid.UUID] | None = None,
    list_id: uuid.UUID | None = None,
) -> EnrollReport:
    """Adds leads to a campaign, applying every exclusion rule.

    This is where the workspace-wide dedupe bites: a lead already contacted by
    *any* account in this workspace is not enrolled, because "your colleague
    already messaged them" is the complaint that loses the customer.
    """
    conditions = [Lead.workspace_id == ctx.workspace_id]
    if lead_ids:
        conditions.append(Lead.id.in_(lead_ids))
    elif list_id is not None:
        conditions.append(Lead.list_id == list_id)
    else:
        raise ValidationFailedError("choose a lead list or specific leads to enroll")

    leads = (await db.execute(select(Lead).where(*conditions))).scalars().all()
    if not leads:
        raise ValidationFailedError("no leads matched that selection")

    blocklist = await lead_service.load_blocklist(db, ctx.workspace_id)

    contacted = {
        value.lower()
        for value in (
            await db.execute(
                select(ContactedLead.public_id).where(
                    ContactedLead.workspace_id == ctx.workspace_id
                )
            )
        )
        .scalars()
        .all()
    }
    already = set(
        (
            await db.execute(
                select(CampaignLead.lead_id).where(CampaignLead.campaign_id == campaign.id)
            )
        )
        .scalars()
        .all()
    )

    report = EnrollReport()
    first_step = campaign.steps[0] if campaign.steps else None
    now = datetime.now(UTC)

    for lead in leads:
        if lead.id in already:
            report.skipped_already_enrolled += 1
            continue
        if not lead.public_id:
            report.skipped_no_profile += 1
            continue
        if lead.public_id.lower() in contacted:
            report.skipped_duplicate += 1
            continue
        if lead_service.is_blocked(
            blocklist, public_id=lead.public_id, company=lead.company, email=lead.email
        ):
            report.skipped_blocked += 1
            continue

        enrollment = CampaignLead(
            workspace_id=ctx.workspace_id,
            campaign_id=campaign.id,
            lead_id=lead.id,
            linkedin_account_id=campaign.linkedin_account_id,
            state=EnrollmentState.PENDING,
            current_step_index=0,
            # Eligible once the first step's delay has elapsed. A running
            # campaign picks it up on the next tick; a draft waits for launch.
            next_run_at=engine.step_due_at(first_step, now) if first_step else now,
        )
        db.add(enrollment)
        await db.flush()
        enrollment.variant = templating.assign_variant(enrollment.id)
        tracking.log_event(enrollment, EventType.ENROLLED, at=now)
        report.enrolled += 1

    await audit.record(
        db,
        "campaign.leads_enrolled",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="campaign",
        target_id=campaign.id,
        metadata={
            "enrolled": report.enrolled,
            "skipped_duplicate": report.skipped_duplicate,
            "skipped_blocked": report.skipped_blocked,
            "skipped_already_enrolled": report.skipped_already_enrolled,
        },
    )
    return report


async def set_status(
    db: AsyncSession, ctx: WorkspaceContext, campaign: Campaign, status: CampaignStatus
) -> Campaign:
    """Launch, pause, or archive. Launching has preconditions."""
    if status is CampaignStatus.RUNNING:
        if not campaign.steps:
            raise ValidationFailedError("add at least one step before launching")

        account = await db.get(LinkedInAccount, campaign.linkedin_account_id)
        if account is None:
            raise NotFoundError("the campaign's LinkedIn account is gone")
        if account.status is not LinkedInAccountStatus.ACTIVE:
            raise ConflictError(
                f"the LinkedIn account is {account.status.value}; reconnect it before launching"
            )

        enrolled = await db.scalar(
            select(func.count())
            .select_from(CampaignLead)
            .where(CampaignLead.campaign_id == campaign.id)
        )
        if not enrolled:
            raise ValidationFailedError("enroll some leads before launching")

        if campaign.started_at is None:
            campaign.started_at = datetime.now(UTC)

    campaign.status = status
    if status is CampaignStatus.COMPLETED:
        campaign.completed_at = datetime.now(UTC)

    await audit.record(
        db,
        f"campaign.{status.value}",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="campaign",
        target_id=campaign.id,
    )
    return campaign


@dataclass(slots=True)
class CampaignStats:
    enrolled: int = 0
    pending: int = 0
    running: int = 0
    completed: int = 0
    replied: int = 0
    stopped: int = 0
    skipped: int = 0
    failed: int = 0
    invites_sent: int = 0
    accepted: int = 0
    messages_sent: int = 0
    views: int = 0
    tasks_pending: int = 0
    tasks_failed: int = 0

    @property
    def acceptance_rate(self) -> float | None:
        return round(self.accepted / self.invites_sent, 4) if self.invites_sent else None

    @property
    def reply_rate(self) -> float | None:
        base = self.invites_sent or self.enrolled
        return round(self.replied / base, 4) if base else None


async def campaign_stats(db: AsyncSession, campaign: Campaign) -> CampaignStats:
    stats = CampaignStats()

    state_rows = (
        await db.execute(
            select(CampaignLead.state, func.count())
            .where(CampaignLead.campaign_id == campaign.id)
            .group_by(CampaignLead.state)
        )
    ).all()
    for state, count in state_rows:
        stats.enrolled += count
        match state:
            case EnrollmentState.PENDING:
                stats.pending = count
            case EnrollmentState.RUNNING:
                stats.running = count
            case EnrollmentState.COMPLETED:
                stats.completed = count
            case EnrollmentState.REPLIED:
                stats.replied = count
            case EnrollmentState.STOPPED:
                stats.stopped = count
            case EnrollmentState.SKIPPED:
                stats.skipped = count
            case EnrollmentState.FAILED:
                stats.failed = count

    stats.invites_sent = int(
        await db.scalar(
            select(func.count())
            .select_from(CampaignLead)
            .where(
                CampaignLead.campaign_id == campaign.id,
                CampaignLead.invite_sent_at.isnot(None),
            )
        )
        or 0
    )
    stats.accepted = int(
        await db.scalar(
            select(func.count())
            .select_from(CampaignLead)
            .where(
                CampaignLead.campaign_id == campaign.id,
                CampaignLead.accepted_at.isnot(None),
            )
        )
        or 0
    )

    action_rows = (
        await db.execute(
            select(ActionTask.action_type, ActionTask.status, func.count())
            .join(CampaignLead, CampaignLead.id == ActionTask.campaign_lead_id)
            .where(CampaignLead.campaign_id == campaign.id)
            .group_by(ActionTask.action_type, ActionTask.status)
        )
    ).all()
    for action_type, status, count in action_rows:
        if status is TaskStatus.SUCCEEDED and action_type is StepType.MESSAGE:
            stats.messages_sent += count
        if status is TaskStatus.SUCCEEDED and action_type is StepType.VIEW_PROFILE:
            stats.views += count
        if status in (TaskStatus.PENDING, TaskStatus.DISPATCHED):
            stats.tasks_pending += count
        if status is TaskStatus.FAILED:
            stats.tasks_failed += count

    return stats
