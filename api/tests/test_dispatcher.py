"""The dispatcher and sequence engine end to end, against a real database.

This file is the reason the rest of the system can be trusted. It does not test
that code runs — it tests that the volume promises hold *over simulated time*,
which is the only way to catch a cap that leaks one extra invite per day or a
ramp curve that is off by a week.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.linkedin import caps as caps_mod
from app.linkedin import fingerprint as fp_mod
from app.linkedin.classify import Classification, ResponseClass
from app.models.campaigns import (
    ActionTask,
    Campaign,
    CampaignLead,
    CampaignStatus,
    CampaignStep,
    ConditionFailAction,
    EnrollmentState,
    StepCondition,
    StepType,
    TaskStatus,
)
from app.models.leads import ContactedLead, Lead
from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus
from app.models.tenancy import User, Workspace
from app.scheduler import dispatcher, engine, pacing, quota

# A Tuesday, 09:30 UTC — inside the default working window.
START = datetime(2026, 9, 15, 9, 30, tzinfo=UTC)


# ── fixtures built directly, for speed ───────────────────────────────────────


def make_workspace(db: Session, *, paused: bool = False) -> Workspace:
    workspace = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}", outreach_paused=paused)
    db.add(workspace)
    db.flush()
    return workspace


def make_user(db: Session) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    db.add(user)
    db.flush()
    return user


def make_account(
    db: Session,
    workspace: Workspace,
    *,
    daily_invites: int = 50,
    age_days: int = 60,
    test_mode: bool = False,
    status: LinkedInAccountStatus = LinkedInAccountStatus.ACTIVE,
) -> LinkedInAccount:
    account = LinkedInAccount(
        workspace_id=workspace.id,
        label="Sender",
        status=status,
        session_ciphertext=b"ciphertext",
        fingerprint=fp_mod.generate(),
        caps=caps_mod.default_caps()
        | {
            "daily_invites": daily_invites,
            "daily_messages": 50,
            "daily_views": 100,
            # A wide window so the simulation is not dominated by clock edges.
            "working_hours": {"start": "08:00", "end": "20:00"},
            "weekdays_only": False,
        },
        test_mode=test_mode,
        timezone="UTC",
        ramp_started_at=START - timedelta(days=age_days),
        proxy=None,
    )
    db.add(account)
    db.flush()
    return account


def make_leads(db: Session, workspace: Workspace, count: int) -> list[Lead]:
    leads = [
        Lead(
            workspace_id=workspace.id,
            public_id=f"lead-{uuid.uuid4().hex[:12]}",
            linkedin_urn=f"urn:li:fsd_profile:{uuid.uuid4().hex[:12]}",
            first_name="Test",
            last_name=f"Lead{index}",
            company="Northwind",
        )
        for index in range(count)
    ]
    db.add_all(leads)
    db.flush()
    return leads


def make_campaign(
    db: Session,
    workspace: Workspace,
    account: LinkedInAccount,
    steps: list[tuple[StepType, int, StepCondition]],
    *,
    status: CampaignStatus = CampaignStatus.RUNNING,
    stop_on_reply: bool = True,
) -> Campaign:
    campaign = Campaign(
        workspace_id=workspace.id,
        linkedin_account_id=account.id,
        name="Test campaign",
        status=status,
        stop_on_reply=stop_on_reply,
        started_at=START,
    )
    db.add(campaign)
    db.flush()
    for index, (step_type, delay, condition) in enumerate(steps):
        db.add(
            CampaignStep(
                campaign_id=campaign.id,
                order_index=index,
                step_type=step_type,
                delay_hours=delay,
                only_if=condition,
                on_condition_fail=ConditionFailAction.SKIP,
                template="Hi {{first_name}}" if step_type is not StepType.VIEW_PROFILE else "",
            )
        )
    db.flush()
    db.refresh(campaign, ["steps"])
    return campaign


def enroll(
    db: Session, campaign: Campaign, account: LinkedInAccount, leads: list[Lead]
) -> list[CampaignLead]:
    enrollments = [
        CampaignLead(
            workspace_id=campaign.workspace_id,
            campaign_id=campaign.id,
            lead_id=lead.id,
            linkedin_account_id=account.id,
            state=EnrollmentState.PENDING,
            current_step_index=0,
            next_run_at=START,
        )
        for lead in leads
    ]
    db.add_all(enrollments)
    db.flush()
    return enrollments


def complete_task(db: Session, task: ActionTask, now: datetime) -> None:
    """Simulates a successful execution without touching LinkedIn.

    Mirrors what `worker.tasks.actions._on_success` does, so the simulation
    exercises the real quota and enrollment transitions.
    """
    account = db.get(LinkedInAccount, task.linkedin_account_id)
    assert account is not None
    enrollment = db.get(CampaignLead, task.campaign_lead_id)
    campaign = db.get(Campaign, enrollment.campaign_id) if enrollment else None

    task.status = TaskStatus.SUCCEEDED
    task.finished_at = now
    quota.consume(db, account, task.action_type, now=now)

    if enrollment is not None:
        enrollment.last_action_at = now
        if task.action_type is StepType.INVITE:
            enrollment.invite_sent_at = now
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

    account.next_allowed_at = pacing.next_allowed_at(now)
    db.flush()


def advance(
    db: Session,
    start: datetime,
    *,
    minutes: int = 20,
    steps: int = 40,
    complete: bool = True,
    stop_after: int | None = None,
) -> tuple[list[ActionTask], datetime]:
    """Runs dispatcher ticks forward through simulated time.

    A materialised task is scheduled at a *jittered* moment inside the working
    window, so it is deliberately not dispatchable in the same tick that
    created it. Tests therefore have to move the clock rather than assume
    same-tick execution.
    """
    now = start
    dispatched: list[ActionTask] = []

    for _ in range(steps):
        dispatcher.tick(db, now=now, send=False)
        db.flush()

        for task in (
            db.execute(select(ActionTask).where(ActionTask.status == TaskStatus.DISPATCHED))
            .scalars()
            .all()
        ):
            dispatched.append(task)
            if complete:
                complete_task(db, task, now)

        if stop_after is not None and len(dispatched) >= stop_after:
            return dispatched, now

        # Jump to the next moment anything could happen, rather than stepping a
        # fixed interval: pacing jitter means a fixed step makes these tests
        # flaky for reasons that have nothing to do with what they assert.
        candidates = [
            value
            for value in (
                db.scalar(
                    select(func.min(ActionTask.scheduled_at)).where(
                        ActionTask.status == TaskStatus.PENDING,
                        ActionTask.scheduled_at > now,
                    )
                ),
                db.scalar(
                    select(func.min(CampaignLead.next_run_at)).where(CampaignLead.next_run_at > now)
                ),
                db.scalar(
                    select(func.min(LinkedInAccount.next_allowed_at)).where(
                        LinkedInAccount.next_allowed_at > now
                    )
                ),
            )
            if value is not None
        ]
        now = min(candidates) if candidates else now + timedelta(minutes=minutes)

    return dispatched, now


# ── the simulated-clock test ─────────────────────────────────────────────────


def test_caps_hold_over_thirty_simulated_days(sdb: Session) -> None:
    """The load-bearing test.

    Runs two accounts through 30 days of ticks with more leads than they could
    ever contact, and asserts the four promises: the daily cap, the trailing
    7-day invite ceiling, the ramp curve, and one action at a time per account.
    """
    workspace = make_workspace(sdb)

    mature = make_account(sdb, workspace, daily_invites=20, age_days=60)
    fresh = make_account(sdb, workspace, daily_invites=75, age_days=0)

    per_account_invites: dict[uuid.UUID, dict[str, int]] = {
        mature.id: defaultdict(int),
        fresh.id: defaultdict(int),
    }

    for account in (mature, fresh):
        leads = make_leads(sdb, workspace, 400)
        campaign = make_campaign(
            sdb, workspace, account, [(StepType.INVITE, 0, StepCondition.ALWAYS)]
        )
        enroll(sdb, campaign, account, leads)

    now = START
    end = START + timedelta(days=30)
    concurrent_violations = 0

    while now < end:
        report = dispatcher.tick(sdb, now=now, send=False)
        sdb.flush()

        dispatched = (
            sdb.execute(select(ActionTask).where(ActionTask.status == TaskStatus.DISPATCHED))
            .scalars()
            .all()
        )

        # One account never has two actions in flight simultaneously.
        by_account: dict[uuid.UUID, int] = defaultdict(int)
        for task in dispatched:
            by_account[task.linkedin_account_id] += 1
        if any(count > 1 for count in by_account.values()):
            concurrent_violations += 1

        for task in dispatched:
            local_day = now.astimezone(
                caps_mod.zone_for(sdb.get(LinkedInAccount, task.linkedin_account_id))
            ).date()
            if task.action_type is StepType.INVITE:
                per_account_invites[task.linkedin_account_id][str(local_day)] += 1
            complete_task(sdb, task, now)

        _ = report
        now += timedelta(minutes=20)

    assert concurrent_violations == 0, "two actions were in flight for one account"

    # 1. No day ever exceeds that account's effective daily cap.
    for account, expected_cap in ((mature, 20), (fresh, None)):
        for day, count in per_account_invites[account.id].items():
            cap = expected_cap if expected_cap is not None else 75
            assert count <= cap, f"{day}: {count} invites exceeded the cap of {cap}"

    # 2. The trailing 7-day ceiling holds for every window, not just on average.
    #    The window must be built from *calendar* dates: a day the cap blocked
    #    entirely has no entry, and indexing the non-empty days would silently
    #    stretch a "7-day" window across nine actual days.
    for account in (mature, fresh):
        counts = per_account_invites[account.id]
        if not counts:
            continue
        first = date.fromisoformat(min(counts))
        last = date.fromisoformat(max(counts))

        day = first
        while day <= last:
            window_total = sum(
                counts.get((day - timedelta(days=offset)).isoformat(), 0) for offset in range(7)
            )
            assert window_total <= settings.safety_max_weekly_invites, (
                f"the 7 calendar days ending {day} sent {window_total} invites, "
                f"over the {settings.safety_max_weekly_invites} ceiling"
            )
            day += timedelta(days=1)

    # 3. The young account is held to the ramp curve on its first days.
    fresh_days = sorted(per_account_invites[fresh.id])
    if fresh_days:
        first_day_count = per_account_invites[fresh.id][fresh_days[0]]
        assert first_day_count <= 12, (
            f"a brand-new account sent {first_day_count} invites on day one; "
            "the ramp curve allows 12"
        )

    # 4. Work actually happened — a test that blocks everything proves nothing.
    total_sent = sum(sum(days.values()) for days in per_account_invites.values())
    assert total_sent > 60, f"only {total_sent} invites went out across 30 days"


# ── gates, individually ──────────────────────────────────────────────────────


def test_workspace_kill_switch_blocks_everything(sdb: Session) -> None:
    workspace = make_workspace(sdb, paused=True)
    account = make_account(sdb, workspace)
    leads = make_leads(sdb, workspace, 3)
    campaign = make_campaign(sdb, workspace, account, [(StepType.INVITE, 0, StepCondition.ALWAYS)])
    enroll(sdb, campaign, account, leads)

    # The gate is the unit under test, and it is the first one checked.
    assert dispatcher.evaluate_gates(sdb, account, workspace, START) == (
        "workspace kill switch is on"
    )

    # And across a simulated day, nothing goes out.
    dispatched, _ = advance(sdb, START, steps=40)
    assert dispatched == []


def test_outside_working_hours_nothing_is_dispatched(sdb: Session) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    account.caps = dict(account.caps) | {"working_hours": {"start": "09:00", "end": "17:00"}}
    leads = make_leads(sdb, workspace, 3)
    campaign = make_campaign(sdb, workspace, account, [(StepType.INVITE, 0, StepCondition.ALWAYS)])
    enroll(sdb, campaign, account, leads)

    # 03:00 UTC, well outside the window.
    report = dispatcher.tick(sdb, now=START.replace(hour=3), send=False)

    assert report.dispatched == 0


def test_a_paused_campaign_does_not_advance(sdb: Session) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    leads = make_leads(sdb, workspace, 3)
    campaign = make_campaign(
        sdb,
        workspace,
        account,
        [(StepType.INVITE, 0, StepCondition.ALWAYS)],
        status=CampaignStatus.PAUSED,
    )
    enroll(sdb, campaign, account, leads)

    report = dispatcher.tick(sdb, now=START, send=False)

    assert report.dispatched == 0
    assert report.enrollment["tasks_created"] == 0


def test_a_blocked_account_dispatches_nothing(sdb: Session) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace, status=LinkedInAccountStatus.BLOCKED)
    leads = make_leads(sdb, workspace, 2)
    campaign = make_campaign(sdb, workspace, account, [(StepType.INVITE, 0, StepCondition.ALWAYS)])
    enroll(sdb, campaign, account, leads)

    report = dispatcher.tick(sdb, now=START, send=False)

    assert report.dispatched == 0


def test_test_mode_caps_the_day_at_the_warmup_range(sdb: Session) -> None:
    """The switch the product promises for dogfooding on a real account."""
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace, daily_invites=75, test_mode=True)
    leads = make_leads(sdb, workspace, 20)
    campaign = make_campaign(sdb, workspace, account, [(StepType.INVITE, 0, StepCondition.ALWAYS)])
    enroll(sdb, campaign, account, leads)

    now = START
    sent = 0
    for _ in range(200):  # a whole day of ticks
        dispatcher.tick(sdb, now=now, send=False)
        sdb.flush()
        for task in (
            sdb.execute(select(ActionTask).where(ActionTask.status == TaskStatus.DISPATCHED))
            .scalars()
            .all()
        ):
            sent += 1
            complete_task(sdb, task, now)
        now += timedelta(minutes=5)
        if now - START > timedelta(hours=11):
            break

    assert (
        settings.safety_test_mode_daily_invites
        <= sent
        <= settings.safety_test_mode_daily_invites_max
    )


# ── the sequence engine ──────────────────────────────────────────────────────


def test_a_reply_stops_the_sequence(sdb: Session) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    leads = make_leads(sdb, workspace, 1)
    campaign = make_campaign(
        sdb,
        workspace,
        account,
        [
            (StepType.INVITE, 0, StepCondition.ALWAYS),
            (StepType.MESSAGE, 0, StepCondition.ALWAYS),
        ],
    )
    enrollment = enroll(sdb, campaign, account, leads)[0]

    # The invite goes out.
    sent, after_invite = advance(sdb, START, steps=20, stop_after=1)
    assert len(sent) == 1 and sent[0].action_type is StepType.INVITE

    # Then they reply, before the follow-up runs.
    enrollment.replied_at = after_invite + timedelta(minutes=30)
    enrollment.next_run_at = after_invite + timedelta(minutes=30)
    sdb.flush()

    advance(sdb, after_invite + timedelta(hours=1), steps=10)

    assert enrollment.state is EnrollmentState.REPLIED
    assert enrollment.next_run_at is None
    # No second task was created for the message step.
    remaining = (
        sdb.execute(
            select(ActionTask).where(
                ActionTask.campaign_lead_id == enrollment.id,
                ActionTask.action_type == StepType.MESSAGE,
            )
        )
        .scalars()
        .all()
    )
    assert remaining == []


def test_an_acceptance_gate_skips_the_step_when_not_accepted(sdb: Session) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    leads = make_leads(sdb, workspace, 1)
    campaign = make_campaign(
        sdb,
        workspace,
        account,
        [
            (StepType.INVITE, 0, StepCondition.ALWAYS),
            (StepType.MESSAGE, 0, StepCondition.IF_ACCEPTED),
        ],
    )
    enrollment = enroll(sdb, campaign, account, leads)[0]

    sent, after_invite = advance(sdb, START, steps=20, stop_after=1)
    assert len(sent) == 1 and sent[0].action_type is StepType.INVITE

    # They never accepted, so the gated message must not be attempted.
    advance(sdb, after_invite + timedelta(hours=1), steps=10)

    messages = (
        sdb.execute(select(ActionTask).where(ActionTask.action_type == StepType.MESSAGE))
        .scalars()
        .all()
    )
    assert messages == []
    assert enrollment.state is EnrollmentState.COMPLETED


def test_an_acceptance_gate_runs_the_step_once_accepted(sdb: Session) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    leads = make_leads(sdb, workspace, 1)
    campaign = make_campaign(
        sdb,
        workspace,
        account,
        [
            (StepType.INVITE, 0, StepCondition.ALWAYS),
            (StepType.MESSAGE, 0, StepCondition.IF_ACCEPTED),
        ],
    )
    enrollment = enroll(sdb, campaign, account, leads)[0]

    sent, after_invite = advance(sdb, START, steps=20, stop_after=1)
    assert len(sent) == 1 and sent[0].action_type is StepType.INVITE

    enrollment.accepted_at = after_invite + timedelta(hours=1)
    enrollment.next_run_at = after_invite + timedelta(hours=1)
    sdb.flush()

    advance(sdb, after_invite + timedelta(hours=2), steps=20, complete=False)

    messages = (
        sdb.execute(select(ActionTask).where(ActionTask.action_type == StepType.MESSAGE))
        .scalars()
        .all()
    )
    assert len(messages) == 1
    assert messages[0].payload["body"] == "Hi Test"


def test_a_missing_template_variable_skips_the_lead_rather_than_sending_a_gap(
    sdb: Session,
) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    lead = make_leads(sdb, workspace, 1)[0]
    lead.first_name = ""  # the template needs it and there is no fallback
    sdb.flush()

    campaign = make_campaign(sdb, workspace, account, [(StepType.MESSAGE, 0, StepCondition.ALWAYS)])
    enrollment = enroll(sdb, campaign, account, [lead])[0]

    dispatcher.tick(sdb, now=START, send=False)
    sdb.flush()

    assert enrollment.state is EnrollmentState.SKIPPED
    assert "first_name" in enrollment.stopped_reason
    tasks = sdb.execute(select(ActionTask)).scalars().all()
    assert tasks == []


def test_idempotency_key_prevents_a_duplicate_invite(sdb: Session) -> None:
    """Redelivery safety. `acks_late` guarantees a killed worker's task returns."""
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    leads = make_leads(sdb, workspace, 1)
    campaign = make_campaign(sdb, workspace, account, [(StepType.INVITE, 0, StepCondition.ALWAYS)])
    enrollment = enroll(sdb, campaign, account, leads)[0]

    dispatcher.tick(sdb, now=START, send=False)
    first = sdb.execute(select(ActionTask)).scalars().all()
    assert len(first) == 1

    # Force the enrollment back to a state where the same step looks due.
    enrollment.next_run_at = START
    enrollment.state = EnrollmentState.RUNNING
    sdb.flush()

    dispatcher.tick(sdb, now=START + timedelta(minutes=1), send=False)

    all_tasks = sdb.execute(select(ActionTask)).scalars().all()
    assert len(all_tasks) == 1, "a second task was created for the same step"
    assert all_tasks[0].idempotency_key == ActionTask.build_idempotency_key(
        enrollment.id, campaign.steps[0].id, 0
    )


def test_a_successful_invite_records_the_contacted_ledger(sdb: Session) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    lead = make_leads(sdb, workspace, 1)[0]
    campaign = make_campaign(sdb, workspace, account, [(StepType.INVITE, 0, StepCondition.ALWAYS)])
    enroll(sdb, campaign, account, [lead])

    sent, _ = advance(sdb, START, steps=20, stop_after=1)
    assert len(sent) == 1

    rows = (
        sdb.execute(select(ContactedLead).where(ContactedLead.workspace_id == workspace.id))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].public_id == lead.public_id


def test_wait_steps_are_walked_without_burning_ticks(sdb: Session) -> None:
    """A tick should pass through no-op steps rather than costing a minute each."""
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    leads = make_leads(sdb, workspace, 1)
    campaign = make_campaign(
        sdb,
        workspace,
        account,
        [
            (StepType.WAIT, 0, StepCondition.ALWAYS),
            (StepType.WAIT, 0, StepCondition.ALWAYS),
            (StepType.INVITE, 0, StepCondition.ALWAYS),
        ],
    )
    enroll(sdb, campaign, account, leads)

    report = dispatcher.tick(sdb, now=START, send=False)
    sdb.flush()

    # One tick walked past both wait steps and materialised the invite.
    assert report.enrollment["tasks_created"] == 1
    assert report.enrollment["advanced"] == 2

    sent, _ = advance(sdb, START, steps=20, stop_after=1)
    assert len(sent) == 1


# ── fault injection ──────────────────────────────────────────────────────────


def test_opening_a_circuit_cancels_the_account_backlog(sdb: Session) -> None:
    """A reconnect must not fire a week of stale invites at once."""
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    leads = make_leads(sdb, workspace, 5)
    campaign = make_campaign(sdb, workspace, account, [(StepType.INVITE, 0, StepCondition.ALWAYS)])
    enroll(sdb, campaign, account, leads)

    # Build a backlog across several ticks.
    now = START
    for _ in range(5):
        dispatcher.tick(sdb, now=now, send=False)
        sdb.flush()
        now += timedelta(hours=1)

    pending_before = (
        sdb.execute(
            select(ActionTask).where(
                ActionTask.status.in_([TaskStatus.PENDING, TaskStatus.DISPATCHED])
            )
        )
        .scalars()
        .all()
    )
    assert pending_before, "the test needs a backlog to cancel"

    cancelled = dispatcher.pause_account_work(sdb, account.id, "restricted by LinkedIn")
    sdb.flush()

    assert cancelled == len(pending_before)
    still_live = (
        sdb.execute(
            select(ActionTask).where(
                ActionTask.linkedin_account_id == account.id,
                ActionTask.status.in_([TaskStatus.PENDING, TaskStatus.DISPATCHED]),
            )
        )
        .scalars()
        .all()
    )
    assert still_live == []


def test_a_soft_limit_burns_half_of_todays_remaining_budget(sdb: Session) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace, daily_invites=20)

    verdict = quota.check(sdb, account, StepType.INVITE, now=START)
    assert verdict.allowed
    assert verdict.limit_today == 20

    burned = quota.halve_remaining_today(sdb, account, StepType.INVITE, now=START)
    sdb.flush()

    assert burned == 10
    assert quota.used_today(sdb, account, StepType.INVITE, now=START) == 10


def test_the_weekly_ceiling_blocks_even_when_today_is_empty(sdb: Session) -> None:
    """The constraint most tools miss: pacing daily is not enough."""
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace, daily_invites=20)

    # Six previous days, right up to the weekly ceiling.
    for offset in range(1, 7):
        quota.consume(
            sdb,
            account,
            StepType.INVITE,
            now=START - timedelta(days=offset),
            amount=17,
        )
    sdb.flush()

    verdict = quota.check(sdb, account, StepType.INVITE, now=START)

    assert not verdict.allowed
    assert "7-day" in verdict.reason
    assert verdict.used_this_week >= settings.safety_max_weekly_invites


# ── pacing distribution ──────────────────────────────────────────────────────


def test_gaps_are_right_skewed_not_uniform() -> None:
    """A flat delay histogram is itself a machine signature."""
    import random as _random
    import statistics

    rng = _random.Random(1234)
    samples = [pacing.sample_gap_seconds(rng) for _ in range(4000)]

    assert min(samples) >= settings.safety_min_action_gap_seconds
    assert max(samples) <= settings.safety_max_action_gap_seconds

    mean = statistics.fmean(samples)
    median = statistics.median(samples)
    # Log-normal: the mean sits above the median. A uniform distribution would
    # put them on top of each other.
    assert mean > median * 1.05, f"mean {mean:.0f} vs median {median:.0f} looks uniform"
    assert len(set(samples)) > 500, "too little variation between gaps"


def test_two_accounts_do_not_share_a_schedule(sdb: Session) -> None:
    workspace = make_workspace(sdb)
    first = make_account(sdb, workspace)
    second = make_account(sdb, workspace)

    a = [pacing.schedule_within_working_hours(first, START) for _ in range(30)]
    b = [pacing.schedule_within_working_hours(second, START) for _ in range(30)]

    assert a != b


@pytest.mark.parametrize("hour", [3, 22])
def test_scheduling_outside_hours_moves_into_the_next_window(sdb: Session, hour: int) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    account.caps = dict(account.caps) | {"working_hours": {"start": "09:00", "end": "17:00"}}

    scheduled = pacing.schedule_within_working_hours(account, START.replace(hour=hour))
    local = scheduled.astimezone(caps_mod.zone_for(account))

    assert 9 <= local.hour < 17, f"scheduled at {local:%H:%M}, outside 09:00-17:00"


def test_the_executing_task_does_not_block_itself(sdb: Session) -> None:
    """The regression this exists for.

    The in-flight gate stops the dispatcher handing out a second action while
    one is running. But the *executor* re-checks the same gates, and the task it
    is about to run is already marked DISPATCHED — so without excluding itself
    every action requeued forever and nothing ever sent.
    """
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    leads = make_leads(sdb, workspace, 2)
    campaign = make_campaign(sdb, workspace, account, [(StepType.INVITE, 0, StepCondition.ALWAYS)])
    enroll(sdb, campaign, account, leads)

    dispatched, _ = advance(sdb, START, steps=20, stop_after=1, complete=False)
    assert len(dispatched) == 1
    task = dispatched[0]
    assert task.status is TaskStatus.DISPATCHED

    # What the dispatcher sees: this account is busy, do not send more.
    assert "slot busy" in dispatcher.evaluate_gates(sdb, account, workspace, START)

    # What the executor sees: I am the in-flight task, so I may proceed.
    assert dispatcher.evaluate_gates(sdb, account, workspace, START, exclude_task_id=task.id) == ""


def test_a_second_task_is_still_blocked_while_one_is_in_flight(sdb: Session) -> None:
    """Excluding self must not disable the gate for everyone else."""
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    leads = make_leads(sdb, workspace, 3)
    campaign = make_campaign(sdb, workspace, account, [(StepType.INVITE, 0, StepCondition.ALWAYS)])
    enroll(sdb, campaign, account, leads)

    dispatched, now = advance(sdb, START, steps=20, stop_after=1, complete=False)
    in_flight = dispatched[0]

    # Force the remaining tasks due; the gate must still refuse.
    for pending in (
        sdb.execute(select(ActionTask).where(ActionTask.status == TaskStatus.PENDING))
        .scalars()
        .all()
    ):
        pending.scheduled_at = now
    sdb.flush()

    report = dispatcher.tick(sdb, now=now, send=False)
    sdb.flush()

    assert report.dispatched == 0
    assert any("slot busy" in reason for reason in report.blocked)
    still_dispatched = (
        sdb.execute(select(ActionTask).where(ActionTask.status == TaskStatus.DISPATCHED))
        .scalars()
        .all()
    )
    assert [t.id for t in still_dispatched] == [in_flight.id]


def test_health_and_dispatch_disagreeing_is_impossible(sdb: Session) -> None:
    """A circuit-opening response must immediately close the dispatch gate."""
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    from app.linkedin import health

    assert dispatcher.evaluate_gates(sdb, account, workspace, START) == ""

    health.apply_classification(
        account, Classification(ResponseClass.BLOCKED, detail="999"), now=START
    )
    sdb.flush()

    assert dispatcher.evaluate_gates(sdb, account, workspace, START) != ""


def test_step_delay_prefers_minutes_override_over_hours() -> None:
    from app.models.campaigns import CampaignStep
    from app.scheduler.engine import step_delay

    assert step_delay(CampaignStep(delay_hours=6, config={})) == timedelta(hours=6)
    assert step_delay(CampaignStep(delay_hours=6, config={"delay_minutes": 10})) == timedelta(
        minutes=10
    )
    assert step_delay(CampaignStep(delay_hours=6, config={"delay_minutes": "x"})) == timedelta(
        hours=6
    )


def test_step_timing_modes() -> None:
    from app.models.campaigns import CampaignStep
    from app.scheduler.engine import step_due_at

    now = START
    smart = CampaignStep(delay_hours=2, config={})
    asap = CampaignStep(delay_hours=48, config={"timing": "asap"})
    delay = CampaignStep(delay_hours=0, config={"timing": "delay", "delay_minutes": 10})
    when = now + timedelta(days=3)
    at = CampaignStep(delay_hours=0, config={"timing": "at", "send_at": when.isoformat()})
    past = CampaignStep(
        delay_hours=0, config={"timing": "at", "send_at": (now - timedelta(days=1)).isoformat()}
    )

    assert step_due_at(smart, now) == now + timedelta(hours=2)
    assert step_due_at(asap, now) == now  # ignores the stored delay
    assert step_due_at(delay, now) == now + timedelta(minutes=10)
    assert step_due_at(at, now) == when
    assert step_due_at(past, now) == now  # a time already gone means "now", not the past


# ── handing tasks to workers ─────────────────────────────────────────────────


def test_an_asap_task_reaches_a_worker_only_after_it_is_saved(
    sdb: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The regression behind "the invitation is not going".

    An "as soon as possible" step is created and claimed in the same tick. If
    the worker is told before that transaction commits, it looks the task up,
    finds nothing, and drops it, while the row stays DISPATCHED and blocks the
    account for good. So the commit must come first.
    """
    from app.worker.tasks import actions

    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    leads = make_leads(sdb, workspace, 1)
    campaign = make_campaign(sdb, workspace, account, [(StepType.INVITE, 0, StepCondition.ALWAYS)])
    for step in campaign.steps:
        step.config = {"timing": "asap"}
    sdb.flush()
    enroll(sdb, campaign, account, leads)

    order: list[str] = []
    monkeypatch.setattr(sdb, "commit", lambda: order.append("commit"))
    monkeypatch.setattr(
        actions.execute_action, "apply_async", lambda *a, **k: order.append("send")
    )

    report = dispatcher.tick(sdb, now=START, send=True)

    assert report.dispatched == 1, "the task should be created and claimed in one tick"
    assert order == ["commit", "send"]


def test_a_task_a_worker_never_ran_is_put_back(sdb: Session) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    leads = make_leads(sdb, workspace, 1)
    campaign = make_campaign(sdb, workspace, account, [(StepType.INVITE, 0, StepCondition.ALWAYS)])
    enroll(sdb, campaign, account, leads)
    dispatched, _ = advance(sdb, START, steps=20, stop_after=1, complete=False)
    task = dispatched[0]
    assert task.status is TaskStatus.DISPATCHED

    # Still fresh: a worker may be running it right now.
    assert dispatcher.recover_stuck(sdb, task.dispatched_at + timedelta(minutes=5)) == 0
    assert task.status is TaskStatus.DISPATCHED

    # Long past any worker's time limit: it was lost, so it goes back in the queue.
    later = task.dispatched_at + dispatcher.STUCK_AFTER + timedelta(minutes=1)
    assert dispatcher.recover_stuck(sdb, later) == 1
    assert task.status is TaskStatus.PENDING
    # ...and the account is no longer treated as busy.
    assert dispatcher.evaluate_gates(sdb, account, workspace, START) == ""


def test_a_task_that_keeps_getting_lost_eventually_fails(sdb: Session) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    leads = make_leads(sdb, workspace, 1)
    campaign = make_campaign(sdb, workspace, account, [(StepType.INVITE, 0, StepCondition.ALWAYS)])
    enroll(sdb, campaign, account, leads)
    dispatched, _ = advance(sdb, START, steps=20, stop_after=1, complete=False)
    task = dispatched[0]
    task.attempts = dispatcher.MAX_DISPATCH_ATTEMPTS

    later = task.dispatched_at + dispatcher.STUCK_AFTER + timedelta(minutes=1)
    dispatcher.recover_stuck(sdb, later)

    assert task.status is TaskStatus.FAILED
    assert task.error_class == "lost"


# ── waiting for an acceptance ────────────────────────────────────────────────


def _invited_lead(sdb: Session) -> tuple[CampaignLead, datetime]:
    """One lead whose invite has been sent, followed by a message gated on acceptance."""
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    leads = make_leads(sdb, workspace, 1)
    campaign = make_campaign(
        sdb,
        workspace,
        account,
        [
            (StepType.INVITE, 0, StepCondition.ALWAYS),
            (StepType.MESSAGE, 0, StepCondition.IF_ACCEPTED),
        ],
    )
    enrollment = enroll(sdb, campaign, account, leads)[0]
    sent, after_invite = advance(sdb, START, steps=20, stop_after=1)
    assert len(sent) == 1 and sent[0].action_type is StepType.INVITE
    # What the executor records when an invite goes out: it is now being watched.
    enrollment.connection_state = "pending"
    sdb.flush()
    return enrollment, after_invite


def _messages(sdb: Session) -> list[ActionTask]:
    return list(
        sdb.execute(select(ActionTask).where(ActionTask.action_type == StepType.MESSAGE))
        .scalars()
        .all()
    )


def test_a_message_gated_on_acceptance_waits_while_the_invite_is_pending(sdb: Session) -> None:
    """Right after an invite nobody has accepted yet. That is "not yet", not "no":
    the step must wait, not be skipped and the sequence ended."""
    enrollment, after_invite = _invited_lead(sdb)

    advance(sdb, after_invite + timedelta(days=3), steps=10, complete=False)

    assert _messages(sdb) == []
    assert not enrollment.state.is_terminal
    assert enrollment.next_run_at is not None


def test_the_waiting_message_goes_out_once_they_accept(sdb: Session) -> None:
    enrollment, after_invite = _invited_lead(sdb)
    advance(sdb, after_invite + timedelta(days=1), steps=5, complete=False)
    assert _messages(sdb) == []

    # What the invite tracker does on seeing them connected.
    accepted = after_invite + timedelta(days=2)
    enrollment.accepted_at = accepted
    enrollment.connection_state = "connected"
    enrollment.next_run_at = accepted
    sdb.flush()

    advance(sdb, accepted + timedelta(minutes=5), steps=20, complete=False)

    assert len(_messages(sdb)) == 1


def test_a_message_gated_on_acceptance_is_dropped_once_the_invite_is_settled_unanswered(
    sdb: Session,
) -> None:
    enrollment, after_invite = _invited_lead(sdb)
    settled = after_invite + timedelta(days=5)
    enrollment.connection_state = "not_accepted"
    enrollment.next_run_at = settled
    sdb.flush()

    advance(sdb, settled + timedelta(minutes=5), steps=10, complete=False)

    assert _messages(sdb) == []
    assert enrollment.state is EnrollmentState.COMPLETED


# ── a page that would not behave ─────────────────────────────────────────────


def _failed_invite(sdb: Session, attempts: int) -> tuple[ActionTask, CampaignLead]:
    from app.linkedin.driver import ActionResult
    from app.worker.tasks import actions

    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    leads = make_leads(sdb, workspace, 1)
    campaign = make_campaign(
        sdb,
        workspace,
        account,
        [
            (StepType.INVITE, 0, StepCondition.ALWAYS),
            (StepType.MESSAGE, 0, StepCondition.IF_ACCEPTED),
        ],
    )
    enrollment = enroll(sdb, campaign, account, leads)[0]
    dispatched, _ = advance(sdb, START, steps=20, stop_after=1, complete=False)
    task = dispatched[0]
    task.attempts = attempts

    result = ActionResult(
        classification=Classification(
            ResponseClass.UNKNOWN_SHAPE, detail="invite click did not open the invitation dialog"
        )
    )
    actions._on_failure(sdb, task, account, enrollment, campaign, result, START)
    return task, enrollment


def test_an_invite_that_hit_a_page_glitch_is_tried_again(sdb: Session) -> None:
    """Giving up on the invite would skip every later step for that person."""
    task, enrollment = _failed_invite(sdb, attempts=1)

    assert task.status is TaskStatus.PENDING
    assert enrollment.current_step_index == 0  # still waiting to send the invite


def test_an_invite_that_keeps_failing_is_eventually_given_up(sdb: Session) -> None:
    from app.worker.tasks import actions

    task, _ = _failed_invite(sdb, attempts=actions.GLITCH_ATTEMPTS)

    assert task.status is TaskStatus.FAILED
