"""The sequence engine: what happens to a lead, and when.

Campaigns enqueue **intent**, never actions. This module turns an enrollment's
current position into at most one `ActionTask`, and only when every gate passes.
Deciding at the last possible moment is what lets a reply arriving thirty
seconds ago stop a message that was "scheduled" days earlier.

Timing model: `delay_hours` on a step means "wait this long after the previous
step finished, then do this one". So an enrollment's `next_run_at` is when the
*next* step becomes eligible, and the working-hours jitter is applied when the
task is actually created.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.campaigns import (
    ActionTask,
    Campaign,
    CampaignLead,
    CampaignStep,
    ConditionFailAction,
    ConnectionState,
    EnrollmentState,
    EventType,
    StepCondition,
    StepType,
    TaskStatus,
)
from app.models.leads import ContactedLead, Lead
from app.models.linkedin import LinkedInAccount
from app.scheduler import pacing, templating
from app.services import tracking

log = get_logger(__name__)


@dataclass(slots=True)
class MaterializeResult:
    task: ActionTask | None
    advanced: bool
    note: str = ""


# How often a step waiting on an answer is looked at again. It costs one database
# read, not a LinkedIn request; an acceptance also wakes the enrollment at once.
WAIT_RECHECK = timedelta(minutes=30)


def evaluate_condition(condition: StepCondition, enrollment: CampaignLead) -> bool:
    """Whether a gated step may run for this enrollment."""
    match condition:
        case StepCondition.ALWAYS:
            return True
        case StepCondition.IF_ACCEPTED:
            return enrollment.accepted_at is not None
        case StepCondition.IF_NOT_ACCEPTED:
            return enrollment.accepted_at is None
        case StepCondition.IF_REPLIED:
            return enrollment.replied_at is not None
        case StepCondition.IF_NOT_REPLIED:
            return enrollment.replied_at is None
    return True


def _step_at(campaign: Campaign, index: int) -> CampaignStep | None:
    steps = campaign.steps
    return steps[index] if 0 <= index < len(steps) else None


def _finish(enrollment: CampaignLead, state: EnrollmentState, reason: str, now: datetime) -> None:
    enrollment.state = state
    enrollment.stopped_reason = reason[:200]
    enrollment.next_run_at = None
    enrollment.completed_at = now
    tracking.log_event(
        enrollment, EventType.SEQUENCE_ENDED, f"{state.value}: {reason}", at=now
    )


def step_delay(step: CampaignStep) -> timedelta:
    """How long to wait before this step. `config["delay_minutes"]` overrides
    `delay_hours` so short gaps (testing, quick follow-ups) need no schema change."""
    minutes = (step.config or {}).get("delay_minutes")
    if isinstance(minutes, int) and minutes >= 0:
        return timedelta(minutes=minutes)
    return timedelta(hours=step.delay_hours)


def step_timing(step: CampaignStep) -> str:
    """ "smart" | "asap" | "delay" | "at" — how the user asked this step to be timed."""
    return str((step.config or {}).get("timing", "smart"))


def step_due_at(step: CampaignStep, now: datetime) -> datetime:
    """When this step becomes eligible, given the previous step just finished at `now`."""
    config = step.config or {}
    timing = step_timing(step)
    if timing == "asap":
        return now
    if timing == "at":
        raw = config.get("send_at")
        if isinstance(raw, str):
            try:
                when = datetime.fromisoformat(raw)
            except ValueError:
                return now
            if when.tzinfo is None:
                when = when.replace(tzinfo=UTC)
            return max(when, now)
        return now
    return now + step_delay(step)


def advance_to_next_step(enrollment: CampaignLead, campaign: Campaign, now: datetime) -> None:
    """Moves the cursor forward and schedules when that step becomes eligible."""
    enrollment.current_step_index += 1
    next_step = _step_at(campaign, enrollment.current_step_index)

    if next_step is None:
        _finish(enrollment, EnrollmentState.COMPLETED, "sequence finished", now)
        return

    enrollment.next_run_at = step_due_at(next_step, now)
    enrollment.state = EnrollmentState.RUNNING


def materialize(
    db: Session,
    enrollment: CampaignLead,
    campaign: Campaign,
    account: LinkedInAccount,
    *,
    now: datetime | None = None,
) -> MaterializeResult:
    """Creates at most one task for this enrollment's current step.

    Returns `advanced=True` when the cursor moved without producing a task
    (a skipped condition or a wait step), so the caller can loop.
    """
    now = now or datetime.now(UTC)

    if enrollment.state.is_terminal:
        return MaterializeResult(task=None, advanced=False, note="enrollment is terminal")

    # A reply ends the sequence, whenever it arrived.
    if campaign.stop_on_reply and enrollment.replied_at is not None:
        _finish(enrollment, EnrollmentState.REPLIED, "the prospect replied", now)
        return MaterializeResult(task=None, advanced=True, note="stopped: replied")

    step = _step_at(campaign, enrollment.current_step_index)
    if step is None:
        _finish(enrollment, EnrollmentState.COMPLETED, "sequence finished", now)
        return MaterializeResult(task=None, advanced=True, note="completed")

    # "Only if they accepted" while the invite is still unanswered means "not yet",
    # not "no": wait for the answer instead of skipping the step for good. The
    # invite tracker settles it (accepted, not accepted or expired) and wakes us.
    if (
        step.only_if is StepCondition.IF_ACCEPTED
        and enrollment.accepted_at is None
        and enrollment.connection_state == ConnectionState.PENDING.value
    ):
        enrollment.next_run_at = now + WAIT_RECHECK
        return MaterializeResult(task=None, advanced=False, note="waiting for acceptance")

    # Gate.
    if not evaluate_condition(step.only_if, enrollment):
        if step.on_condition_fail is ConditionFailAction.STOP:
            _finish(
                enrollment,
                EnrollmentState.STOPPED,
                f"condition {step.only_if.value} not met at step {step.order_index + 1}",
                now,
            )
            return MaterializeResult(task=None, advanced=True, note="stopped by condition")
        advance_to_next_step(enrollment, campaign, now)
        return MaterializeResult(task=None, advanced=True, note="step skipped by condition")

    # A wait step consumes only time.
    if step.step_type is StepType.WAIT:
        advance_to_next_step(enrollment, campaign, now)
        return MaterializeResult(task=None, advanced=True, note="wait elapsed")

    lead = db.get(Lead, enrollment.lead_id)
    if lead is None or not lead.public_id:
        _finish(enrollment, EnrollmentState.SKIPPED, "lead has no LinkedIn profile id", now)
        return MaterializeResult(task=None, advanced=True, note="skipped: no public id")

    # Render now, so the stored payload is exactly what will be sent.
    body = ""
    if step.template:
        context = templating.LeadContext.from_lead(lead, sender_name=account.full_name)
        try:
            body = templating.render(step.template, context, seed=enrollment.id)
        except templating.MissingVariableError as exc:
            # Skipping beats sending "Hi , saw you work at ".
            _finish(
                enrollment,
                EnrollmentState.SKIPPED,
                f"template needs {exc.variable}, which this lead lacks",
                now,
            )
            log.info(
                "engine.skipped_missing_variable",
                enrollment_id=str(enrollment.id),
                variable=exc.variable,
            )
            return MaterializeResult(task=None, advanced=True, note="skipped: missing variable")

        if step.step_type is StepType.INVITE and len(body) > templating.MAX_INVITE_NOTE_CHARS:
            body = body[: templating.MAX_INVITE_NOTE_CHARS].rstrip()

    idempotency_key = ActionTask.build_idempotency_key(enrollment.id, step.id, 0)

    existing = db.scalar(select(ActionTask).where(ActionTask.idempotency_key == idempotency_key))
    if existing is not None:
        # Already materialised — a previous tick got here first.
        return MaterializeResult(task=existing, advanced=False, note="already materialised")

    # "smart" spreads the action to a human-like moment inside working hours.
    # Any other mode means the user chose the timing, so run it when it is due;
    # the dispatcher still applies working hours, daily limits and action spacing.
    if step_timing(step) == "smart":
        scheduled_at = pacing.schedule_within_working_hours(account, now)
    else:
        scheduled_at = now

    task = ActionTask(
        workspace_id=enrollment.workspace_id,
        linkedin_account_id=account.id,
        campaign_lead_id=enrollment.id,
        step_id=step.id,
        action_type=step.step_type,
        payload={
            "public_id": lead.public_id,
            "linkedin_urn": lead.linkedin_urn,
            "body": body,
            "lead_id": str(lead.id),
            "campaign_id": str(campaign.id),
            "step_index": step.order_index,
            "variant": enrollment.variant,
        },
        scheduled_at=scheduled_at,
        status=TaskStatus.PENDING,
        idempotency_key=idempotency_key,
    )
    db.add(task)

    enrollment.state = EnrollmentState.RUNNING
    # Do not re-evaluate this enrollment until the task resolves.
    enrollment.next_run_at = None

    return MaterializeResult(task=task, advanced=False, note="task created")


def materialize_due(
    db: Session, *, now: datetime | None = None, limit: int = 200
) -> dict[str, int]:
    """The enrollment tick: turn due enrollments into tasks.

    Deliberately separate from dispatch. This decides *what* should happen;
    the dispatcher decides *whether it may happen right now*.
    """
    now = now or datetime.now(UTC)
    created = skipped = advanced = 0

    enrollments = list(
        db.execute(
            select(CampaignLead)
            .where(
                CampaignLead.state.in_([EnrollmentState.PENDING, EnrollmentState.RUNNING]),
                CampaignLead.next_run_at.isnot(None),
                CampaignLead.next_run_at <= now,
            )
            .order_by(CampaignLead.next_run_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        .scalars()
        .all()
    )

    for enrollment in enrollments:
        campaign = db.get(Campaign, enrollment.campaign_id)
        account = db.get(LinkedInAccount, enrollment.linkedin_account_id)
        if campaign is None or account is None:
            _finish(enrollment, EnrollmentState.FAILED, "campaign or account is gone", now)
            continue

        from app.models.campaigns import CampaignStatus

        if campaign.status is not CampaignStatus.RUNNING:
            # Paused mid-flight: leave the cursor alone and look again later.
            enrollment.next_run_at = now + timedelta(minutes=15)
            continue

        # A condition or wait step can resolve instantly; loop so one tick can
        # walk past them instead of costing a minute per no-op step.
        for _ in range(10):
            result = materialize(db, enrollment, campaign, account, now=now)
            if result.task is not None:
                created += 1
                break
            if not result.advanced:
                break
            advanced += 1
            if enrollment.state.is_terminal:
                skipped += 1
                break
            if enrollment.next_run_at is not None and enrollment.next_run_at > now:
                break  # the next step is not due yet

    return {
        "enrollments": len(enrollments),
        "tasks_created": created,
        "advanced": advanced,
        "finished": skipped,
    }


def record_contacted(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    public_id: str,
    lead_id: uuid.UUID | None,
    account_id: uuid.UUID | None,
    campaign_id: uuid.UUID | None,
    now: datetime | None = None,
) -> None:
    """Adds someone to the workspace-wide contacted ledger, once.

    Relies on the unique constraint rather than a pre-check: two campaigns
    racing on the same person must not both succeed.
    """
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    stmt = (
        pg_insert(ContactedLead)
        .values(
            id=uuid.uuid4(),
            workspace_id=workspace_id,
            public_id=public_id,
            lead_id=lead_id,
            linkedin_account_id=account_id,
            campaign_id=campaign_id,
            first_contacted_at=now or datetime.now(UTC),
        )
        .on_conflict_do_nothing(index_elements=["workspace_id", "public_id"])
    )
    db.execute(stmt)
