"""The dispatcher: the only thing that decides an action may happen now.

Runs every 60 seconds. For each account with due work it walks the gates, in
this order, and the first failure wins:

  1. workspace kill switch
  2. account status (active, not paused/blocked/challenged)
  3. circuit breaker
  4. the single execution slot (is this account already acting?)
  5. pacing — has the log-normal gap elapsed?
  6. working hours, in the account's own timezone
  7. quota — daily cap, then the trailing 7-day invite ceiling

Only then is one task claimed and handed to a worker. **One task per account
per tick**, because an account has one execution slot and dispatching two would
mean one of them waits while holding a worker.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.linkedin import caps as caps_mod
from app.linkedin import health
from app.models.campaigns import ActionTask, TaskStatus
from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus
from app.models.tenancy import Workspace
from app.scheduler import locks, quota

log = get_logger(__name__)


@dataclass(slots=True)
class DispatchDecision:
    account_id: uuid.UUID
    dispatched: bool
    task_id: uuid.UUID | None = None
    blocked_by: str = ""


# A dispatched action is either running or already lost. Celery's hard limit on an
# action is 10 minutes, so a task still DISPATCHED after this long has no worker.
STUCK_AFTER = timedelta(minutes=15)
MAX_DISPATCH_ATTEMPTS = 5


@dataclass(slots=True)
class TickReport:
    considered: int = 0
    dispatched: int = 0
    recovered: int = 0
    blocked: dict[str, int] = field(default_factory=dict)
    enrollment: dict[str, int] = field(default_factory=dict)
    # Tasks handed out this tick; sent to workers only once they are saved.
    task_ids: list[uuid.UUID] = field(default_factory=list)

    def note_block(self, reason: str) -> None:
        # Bucket by the gate name, not the full message: "outside working hours"
        # rather than a thousand distinct timestamps.
        key = reason.split(":")[0].split("(")[0].strip()
        self.blocked[key] = self.blocked.get(key, 0) + 1

    def as_dict(self) -> dict[str, object]:
        return {
            "accounts_considered": self.considered,
            "tasks_dispatched": self.dispatched,
            "recovered": self.recovered,
            "blocked": self.blocked,
            "enrollment": self.enrollment,
        }


def _accounts_with_due_work(db: Session, now: datetime) -> list[LinkedInAccount]:
    """Accounts that have at least one task due, cheapest query first.

    Starting from tasks rather than from accounts means an installation with
    10,000 idle accounts does no work for them.
    """
    account_ids = (
        db.execute(
            select(ActionTask.linkedin_account_id)
            .where(
                ActionTask.status == TaskStatus.PENDING,
                ActionTask.scheduled_at <= now,
            )
            .group_by(ActionTask.linkedin_account_id)
        )
        .scalars()
        .all()
    )
    if not account_ids:
        return []

    return list(
        db.execute(select(LinkedInAccount).where(LinkedInAccount.id.in_(account_ids)))
        .scalars()
        .all()
    )


def _claim_next_task(db: Session, account: LinkedInAccount, now: datetime) -> ActionTask | None:
    """Claims one due task for this account.

    `FOR UPDATE SKIP LOCKED` so two dispatcher replicas never hand the same
    task to two workers.
    """
    task = db.execute(
        select(ActionTask)
        .where(
            ActionTask.linkedin_account_id == account.id,
            ActionTask.status == TaskStatus.PENDING,
            ActionTask.scheduled_at <= now,
        )
        .order_by(ActionTask.scheduled_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    ).scalar_one_or_none()
    return task


def evaluate_gates(
    db: Session,
    account: LinkedInAccount,
    workspace: Workspace | None,
    now: datetime,
    *,
    exclude_task_id: uuid.UUID | None = None,
) -> str:
    """Returns "" when the account may act, otherwise the blocking reason.

    `exclude_task_id` is required when the *executor* re-checks the gates: the
    task it is about to run is itself already marked DISPATCHED, so without
    excluding it the in-flight check would see the task blocking itself and
    requeue it forever.
    """
    if workspace is None:
        return "workspace missing"
    if workspace.outreach_paused:
        return "workspace kill switch is on"

    allowed, reason = health.can_dispatch(account, now=now)
    if not allowed:
        return reason

    if locks.is_held(account.id):
        return "slot busy: the account is already performing an action"

    # Belt and braces on the single-slot rule. The Redis lock is taken by the
    # *worker*, so between dispatch and the worker starting there is a window
    # where the lock is free but an action is already in flight. The task table
    # is the durable record of that, so it is checked too.
    in_flight_query = (
        select(func.count())
        .select_from(ActionTask)
        .where(
            ActionTask.linkedin_account_id == account.id,
            ActionTask.status == TaskStatus.DISPATCHED,
        )
    )
    if exclude_task_id is not None:
        in_flight_query = in_flight_query.where(ActionTask.id != exclude_task_id)

    if db.scalar(in_flight_query):
        return "slot busy: an action is already dispatched for this account"

    in_hours, hours_reason = caps_mod.within_working_hours(account, now=now)
    if not in_hours:
        return hours_reason

    return ""


def dispatch_for_account(
    db: Session,
    account: LinkedInAccount,
    workspace: Workspace | None,
    now: datetime,
) -> DispatchDecision:
    """Walks the gates for one account and claims at most one task.

    Claiming only marks the row DISPATCHED. Handing it to a worker is the
    caller's job, and it must happen after the transaction commits: a worker
    that looks for the row first finds nothing and drops the task.
    """
    blocked = evaluate_gates(db, account, workspace, now)
    if blocked:
        return DispatchDecision(account_id=account.id, dispatched=False, blocked_by=blocked)

    task = _claim_next_task(db, account, now)
    if task is None:
        return DispatchDecision(account_id=account.id, dispatched=False, blocked_by="no due task")

    # Quota is checked against the claimed task's action type, since caps differ
    # per action. A blocked task stays PENDING and is retried after midnight
    # local — no work is lost.
    verdict = quota.check(db, account, task.action_type, now=now)
    if not verdict.allowed:
        return DispatchDecision(account_id=account.id, dispatched=False, blocked_by=verdict.reason)

    task.status = TaskStatus.DISPATCHED
    task.dispatched_at = now
    task.attempts += 1

    return DispatchDecision(account_id=account.id, dispatched=True, task_id=task.id)


def recover_stuck(db: Session, now: datetime) -> int:
    """Puts back tasks that were handed to a worker which never ran them.

    Without this, one lost message leaves a task DISPATCHED forever, and the
    in-flight gate then treats that account as busy for good.
    """
    stuck = list(
        db.execute(
            select(ActionTask).where(
                ActionTask.status == TaskStatus.DISPATCHED,
                ActionTask.dispatched_at.isnot(None),
                ActionTask.dispatched_at < now - STUCK_AFTER,
            )
        )
        .scalars()
        .all()
    )
    for task in stuck:
        if task.attempts >= MAX_DISPATCH_ATTEMPTS:
            task.status = TaskStatus.FAILED
            task.finished_at = now
            task.error_class = "lost"
            task.error_detail = "no worker ran this task after repeated attempts"
        else:
            task.status = TaskStatus.PENDING
            task.scheduled_at = now
            task.error_detail = "recovered: a worker never picked it up"
        log.warning(
            "dispatcher.recovered_stuck_task",
            task_id=str(task.id),
            account_id=str(task.linkedin_account_id),
            attempts=task.attempts,
        )
    if stuck:
        db.flush()  # the gates below read this session, which does not autoflush
    return len(stuck)


def tick(db: Session, *, now: datetime | None = None, send: bool = True) -> TickReport:
    """One dispatcher cycle: recover lost tasks, materialise due enrollments, dispatch."""
    from app.scheduler import engine

    now = now or datetime.now(UTC)
    report = TickReport()
    report.recovered = recover_stuck(db, now)

    # 1. Turn due enrollments into tasks.
    report.enrollment = engine.materialize_due(db, now=now)
    db.flush()

    # 2. Dispatch at most one task per eligible account.
    accounts = _accounts_with_due_work(db, now)
    report.considered = len(accounts)

    workspaces: dict[uuid.UUID, Workspace | None] = {}
    for account in accounts:
        if account.workspace_id not in workspaces:
            workspaces[account.workspace_id] = db.get(Workspace, account.workspace_id)

        decision = dispatch_for_account(db, account, workspaces[account.workspace_id], now)
        if decision.dispatched:
            report.dispatched += 1
            if decision.task_id is not None:
                report.task_ids.append(decision.task_id)
        elif decision.blocked_by and decision.blocked_by != "no due task":
            report.note_block(decision.blocked_by)

    if report.dispatched or report.enrollment.get("tasks_created"):
        log.info("dispatcher.tick", **report.as_dict())

    if send and report.task_ids:
        # Save first, then send. A task created and claimed in this same tick (an
        # "as soon as possible" step) is not visible to a worker until it commits.
        db.commit()
        # Imported here: tests run the dispatcher with send=False, and importing
        # the task module at module scope would drag Celery in.
        from app.worker.tasks.actions import execute_action

        for task_id in report.task_ids:
            execute_action.apply_async(args=[str(task_id)], queue="linkedin.action")

    return report


def pause_account_work(db: Session, account_id: uuid.UUID, reason: str) -> int:
    """Cancels every pending task for an account. Used when a circuit opens.

    Cancelling rather than leaving them pending matters: when the user
    reconnects, a backlog of stale invites must not all fire at once.
    """
    tasks = list(
        db.execute(
            select(ActionTask).where(
                ActionTask.linkedin_account_id == account_id,
                ActionTask.status.in_([TaskStatus.PENDING, TaskStatus.DISPATCHED]),
            )
        )
        .scalars()
        .all()
    )
    for task in tasks:
        task.status = TaskStatus.CANCELLED
        task.error_class = "cancelled"
        task.error_detail = reason[:500]
        task.finished_at = datetime.now(UTC)

    if tasks:
        log.warning(
            "dispatcher.cancelled_pending",
            account_id=str(account_id),
            count=len(tasks),
            reason=reason,
        )
    return len(tasks)


def account_is_operable(account: LinkedInAccount) -> bool:
    return account.status is LinkedInAccountStatus.ACTIVE
