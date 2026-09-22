"""Action execution: the one place an outbound LinkedIn action actually happens.

Shape of every run:

  1. re-check the gates — state can have changed since dispatch, and a reply
     that landed ten seconds ago must cancel a message scheduled days ago;
  2. take the account's single execution slot;
  3. warm the session if this is the first action of a window;
  4. perform exactly one action;
  5. fold the response into health, quota, and the enrollment;
  6. set the next log-normal gap.

`max_retries=0` on the Celery task is deliberate. Retries are decided by the
safety engine and expressed as a re-scheduled `ActionTask`, never by Celery's
blind backoff, which would ignore quotas and circuit state.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db import session_scope
from app.linkedin import build_driver, health
from app.linkedin.classify import Classification, ResponseClass
from app.linkedin.driver import ActionResult, LinkedInDriver
from app.models.campaigns import (
    ActionTask,
    Campaign,
    CampaignLead,
    ConnectionState,
    EnrollmentState,
    EventType,
    StepType,
    TaskStatus,
)
from app.models.leads import Lead
from app.models.linkedin import LinkedInAccount
from app.models.tenancy import NotificationType, Workspace
from app.scheduler import dispatcher, engine, locks, pacing, quota
from app.services import notification_service, tracking
from app.worker.celery_app import celery_app

log = get_logger(__name__)

# How long an account may sit idle before the next action gets a warm-up read
# first. A session whose first request of the day is a write looks nothing like
# a human opening the app.
WARM_AFTER = timedelta(hours=2)
MAX_ATTEMPTS = 5
# A page that would not behave (a button that did nothing) is usually a glitch,
# not a permanent state. An invite gets a couple more tries before it is given up,
# because giving up here skips every later step for that person.
GLITCH_ATTEMPTS = 3


def _requeue(task: ActionTask, account: LinkedInAccount, reason: str) -> None:
    """Puts a task back in the queue without consuming an attempt budget."""
    task.status = TaskStatus.PENDING
    task.error_detail = reason[:500]
    # Respect the account's own next-allowed time so a blocked task does not
    # spin against the same gate every minute.
    task.scheduled_at = max(
        task.scheduled_at,
        account.next_allowed_at or datetime.now(UTC) + timedelta(minutes=5),
    )


def _resolve_urn(
    db: Session, driver: LinkedInDriver, lead: Lead, task: ActionTask
) -> tuple[str, Classification | None]:
    """Invites need the profile's URN id, not the /in/ slug.

    Fetching the profile to learn it is also a genuine profile view, which is a
    perfectly normal thing to do just before connecting with someone.
    """
    if lead.linkedin_urn:
        return lead.linkedin_urn, None

    classification, profile = driver.get_profile(lead.public_id)
    if not classification.ok or profile is None:
        return "", classification

    if profile.urn:
        lead.linkedin_urn = profile.urn
    # Opportunistically fill gaps the CSV did not have.
    lead.first_name = lead.first_name or profile.first_name
    lead.last_name = lead.last_name or profile.last_name
    lead.headline = lead.headline or profile.headline
    lead.company = lead.company or profile.company
    lead.title = lead.title or profile.title
    lead.location = lead.location or profile.location
    lead.enriched = profile.raw or lead.enriched
    lead.enriched_at = datetime.now(UTC)
    _ = db  # the lead is already in this session; explicit for readers

    return lead.linkedin_urn, classification


def _perform(db: Session, driver: LinkedInDriver, task: ActionTask, lead: Lead) -> ActionResult:
    """Dispatches to the right driver call for this action type."""
    public_id = str(task.payload.get("public_id") or lead.public_id)
    body = str(task.payload.get("body") or "")

    match task.action_type:
        case StepType.VIEW_PROFILE:
            return driver.view_profile(public_id)

        case StepType.INVITE:
            urn, failure = _resolve_urn(db, driver, lead, task)
            if not urn:
                return ActionResult(
                    classification=failure
                    or Classification(
                        ResponseClass.NOT_FOUND,
                        detail="could not resolve this profile's LinkedIn id",
                    )
                )
            return driver.send_invitation(urn, body)

        case StepType.MESSAGE:
            urn, failure = _resolve_urn(db, driver, lead, task)
            if not urn:
                return ActionResult(
                    classification=failure
                    or Classification(
                        ResponseClass.NOT_FOUND,
                        detail="could not resolve this profile's LinkedIn id",
                    )
                )
            return driver.send_message(urn, body)

        case StepType.WITHDRAW_INVITE:
            invitation_urn = str(task.payload.get("invitation_urn") or "")
            if not invitation_urn:
                return ActionResult(
                    classification=Classification(
                        ResponseClass.NOT_FOUND, detail="no invitation to withdraw"
                    )
                )
            return driver.withdraw_invitation(invitation_urn)

    return ActionResult(
        classification=Classification(
            ResponseClass.UNKNOWN_SHAPE,
            detail=f"no handler for action type {task.action_type.value}",
        )
    )


def _on_success(
    db: Session,
    task: ActionTask,
    account: LinkedInAccount,
    enrollment: CampaignLead | None,
    campaign: Campaign | None,
    result: ActionResult,
    now: datetime,
) -> None:
    task.status = TaskStatus.SUCCEEDED
    task.finished_at = now
    task.result = {"remote_id": result.remote_id, **result.payload}
    task.error_class = ""
    task.error_detail = ""

    quota.consume(db, account, task.action_type, now=now)

    member_id = str(result.payload.get("member_id") or "")
    lead_id = task.payload.get("lead_id")
    if member_id and lead_id:
        lead = db.get(Lead, lead_id)
        if lead is not None:
            # Lets the inbox link this person's conversation to the lead exactly.
            lead.enriched = {**(lead.enriched or {}), "member_id": member_id}

    if enrollment is not None:
        enrollment.last_action_at = now
        if task.action_type is StepType.VIEW_PROFILE:
            enrollment.viewed_at = enrollment.viewed_at or now
            tracking.log_event(enrollment, EventType.PROFILE_VIEWED, at=now)
        elif task.action_type is StepType.INVITE:
            enrollment.invite_sent_at = now
            # From here the invite is watched until it is answered or expires.
            enrollment.connection_state = ConnectionState.PENDING.value
            enrollment.check_count = 0
            enrollment.next_check_at = tracking.first_check_at(now)
            enrollment.connection_resolved_at = None
            has_note = bool(task.payload.get("body"))
            tracking.log_event(
                enrollment,
                EventType.INVITE_SENT,
                "with a note" if has_note else "without a note",
                at=now,
            )
        elif task.action_type is StepType.MESSAGE:
            tracking.log_event(enrollment, EventType.MESSAGE_SENT, at=now)

        # The contacted ledger is what stops a second campaign — or a colleague's
        # account — reaching the same person.
        if task.action_type in (StepType.INVITE, StepType.MESSAGE):
            engine.record_contacted(
                db,
                workspace_id=task.workspace_id,
                public_id=str(task.payload.get("public_id") or ""),
                lead_id=enrollment.lead_id,
                account_id=account.id,
                campaign_id=enrollment.campaign_id,
                now=now,
            )

        if campaign is not None:
            engine.advance_to_next_step(enrollment, campaign, now)

    # The next action is spaced by a log-normal gap, not a fixed interval.
    account.next_allowed_at = pacing.next_allowed_at(now)
    health.apply_classification(account, result.classification, now=now)

    log.info(
        "action.succeeded",
        task_id=str(task.id),
        action=task.action_type.value,
        account_id=str(account.id),
        next_allowed_at=account.next_allowed_at.isoformat(),
    )


def _on_failure(
    db: Session,
    task: ActionTask,
    account: LinkedInAccount,
    enrollment: CampaignLead | None,
    campaign: Campaign | None,
    result: ActionResult,
    now: datetime,
) -> None:
    classification = result.classification
    outcome = health.apply_classification(account, classification, now=now)

    task.error_class = classification.response_class.value
    task.error_detail = classification.detail[:500]

    if outcome.quota_should_halve:
        burned = quota.halve_remaining_today(db, account, task.action_type, now=now)
        log.warning(
            "action.soft_limit.quota_halved",
            account_id=str(account.id),
            burned=burned,
            action=task.action_type.value,
        )

    if outcome.circuit_opened:
        # Everything queued for this account is cancelled, so a reconnect does
        # not fire a backlog all at once.
        task.status = TaskStatus.CANCELLED
        task.finished_at = now
        dispatcher.pause_account_work(db, account.id, outcome.detail or task.error_class)
        notification_service.create_sync(
            db,
            account.workspace_id,
            NotificationType.ACCOUNT_ACTION_NEEDED,
            f"{account.label or account.public_id or 'A LinkedIn account'} stopped — {outcome.status.value.replace('_', ' ')}",
            body=outcome.detail or "Outreach from this account is paused until you reconnect it.",
            link="/accounts",
        )
        return

    # The profile is gone or private: skip this step rather than retrying.
    if classification.response_class is ResponseClass.NOT_FOUND:
        task.status = TaskStatus.SKIPPED
        task.finished_at = now
        if enrollment is not None:
            tracking.log_event(
                enrollment,
                EventType.ACTION_SKIPPED,
                f"{task.action_type.value}: {classification.detail}",
                at=now,
            )
        if enrollment is not None and campaign is not None:
            engine.advance_to_next_step(enrollment, campaign, now)
        return

    if classification.response_class.is_retryable and task.attempts < MAX_ATTEMPTS:
        _requeue(task, account, classification.detail)
        return

    if (
        task.action_type is StepType.INVITE
        and classification.response_class is ResponseClass.UNKNOWN_SHAPE
        and task.attempts < GLITCH_ATTEMPTS
    ):
        _requeue(task, account, classification.detail)
        return

    task.status = TaskStatus.FAILED
    task.finished_at = now
    if enrollment is not None:
        enrollment.last_error = classification.detail[:500]
        tracking.log_event(
            enrollment,
            EventType.ACTION_FAILED,
            f"{task.action_type.value}: {classification.detail}",
            at=now,
            meta={"error_class": classification.response_class.value, "attempts": task.attempts},
        )
        if campaign is not None:
            # One failed step does not condemn the whole sequence.
            engine.advance_to_next_step(enrollment, campaign, now)

    log.warning(
        "action.failed",
        task_id=str(task.id),
        action=task.action_type.value,
        classification=classification.response_class.value,
        detail=classification.detail,
        attempts=task.attempts,
    )


@celery_app.task(name="linkedin.action.execute", bind=True, max_retries=0)
def execute_action(self: Any, task_id: str) -> dict[str, str]:
    """Executes one `ActionTask`."""
    _ = self
    now = datetime.now(UTC)

    with session_scope() as db:
        task = db.get(ActionTask, task_id)
        if task is None:
            log.warning("action.task_missing", task_id=task_id)
            return {"status": "missing"}
        if task.status is not TaskStatus.DISPATCHED:
            # Redelivery of an already-resolved task. The idempotency key means
            # we can safely do nothing.
            return {"status": f"not dispatched ({task.status.value})"}

        account = db.get(LinkedInAccount, task.linkedin_account_id)
        if account is None:
            task.status = TaskStatus.CANCELLED
            task.error_detail = "account no longer exists"
            return {"status": "cancelled"}

        workspace = db.get(Workspace, task.workspace_id)
        enrollment = db.get(CampaignLead, task.campaign_lead_id) if task.campaign_lead_id else None
        campaign = db.get(Campaign, enrollment.campaign_id) if enrollment else None

        # Re-check every gate. Dispatch may have been a minute ago.
        # Exclude this task: it is already DISPATCHED, and the in-flight gate
        # would otherwise see it blocking itself.
        blocked = dispatcher.evaluate_gates(db, account, workspace, now, exclude_task_id=task.id)
        if blocked:
            _requeue(task, account, blocked)
            return {"status": "requeued", "reason": blocked}

        # A reply that arrived after dispatch must cancel this action.
        if (
            enrollment is not None
            and campaign is not None
            and campaign.stop_on_reply
            and enrollment.replied_at is not None
        ):
            task.status = TaskStatus.CANCELLED
            task.finished_at = now
            task.error_detail = "the prospect replied before this action ran"
            enrollment.state = EnrollmentState.REPLIED
            enrollment.next_run_at = None
            enrollment.completed_at = now
            enrollment.stopped_reason = "the prospect replied"
            return {"status": "cancelled", "reason": "replied"}

        lead = db.get(Lead, task.payload.get("lead_id")) if task.payload.get("lead_id") else None
        if lead is None:
            task.status = TaskStatus.SKIPPED
            task.finished_at = now
            task.error_detail = "lead no longer exists"
            return {"status": "skipped"}

        try:
            with locks.account_slot(account.id):
                driver = build_driver(account)
                try:
                    # Warm a cold session before writing to it.
                    if (
                        account.last_action_at is None or now - account.last_action_at > WARM_AFTER
                    ) and task.action_type is not StepType.VIEW_PROFILE:
                        warm = driver.warm_session()
                        if warm.response_class.opens_circuit:
                            _on_failure(
                                db,
                                task,
                                account,
                                enrollment,
                                campaign,
                                ActionResult(classification=warm),
                                now,
                            )
                            return {"status": "failed", "stage": "warm"}

                    result = _perform(db, driver, task, lead)
                finally:
                    driver.close()
        except locks.SlotBusy:
            _requeue(task, account, "the account was already performing an action")
            return {"status": "requeued", "reason": "slot busy"}

        if result.ok:
            _on_success(db, task, account, enrollment, campaign, result, now)
            return {"status": "succeeded"}

        _on_failure(db, task, account, enrollment, campaign, result, now)
        return {"status": task.status.value, "class": task.error_class}
