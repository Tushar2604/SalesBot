"""Quota accounting against the daily ledger.

Two limits apply to invites simultaneously, and both must pass:

* a **daily** cap, resolved through `caps.resolve` so the ramp curve and the
  safety ceiling are already folded in, and
* a **trailing 7-day** cap of ~100 invites. This is LinkedIn's real constraint
  and the one most tools miss: staying under 20/day still trips it if you never
  take a day off.

Days are the account's *local* days. A "day" that rolls over at UTC midnight
would split an Indian or Australian working day in half.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.linkedin import caps as caps_mod
from app.models.campaigns import ActionTask, DailyQuotaLedger, StepType, TaskStatus
from app.models.linkedin import LinkedInAccount

# Actions that consume a budget. Reads are unlimited by us — LinkedIn's own
# limits apply — because throttling them would make the write/read ratio worse.
BUDGETED: dict[StepType, str] = {
    StepType.INVITE: "daily_invites",
    StepType.MESSAGE: "daily_messages",
    StepType.VIEW_PROFILE: "daily_views",
}


def local_day(account: LinkedInAccount, now: datetime | None = None) -> date:
    now = now or datetime.now(UTC)
    return now.astimezone(caps_mod.zone_for(account)).date()


@dataclass(slots=True)
class QuotaVerdict:
    allowed: bool
    reason: str = ""
    used_today: int = 0
    limit_today: int = 0
    used_this_week: int = 0
    limit_this_week: int = 0


def used_today(
    db: Session, account: LinkedInAccount, action_type: StepType, *, now: datetime | None = None
) -> int:
    """Actions already recorded in the ledger today."""
    day = local_day(account, now)
    value = db.scalar(
        select(DailyQuotaLedger.used).where(
            DailyQuotaLedger.linkedin_account_id == account.id,
            DailyQuotaLedger.day == day,
            DailyQuotaLedger.action_type == action_type,
        )
    )
    return int(value or 0)


def in_flight(db: Session, account: LinkedInAccount, action_type: StepType) -> int:
    """Dispatched-but-unresolved actions.

    These must count against the cap. The ledger is written by the *worker* when
    LinkedIn answers, so between dispatch and completion an action is invisible
    to the ledger — and a second dispatcher tick would happily hand out one more
    than the cap allows. Counting in-flight work closes that window.
    """
    value = db.scalar(
        select(func.count())
        .select_from(ActionTask)
        .where(
            ActionTask.linkedin_account_id == account.id,
            ActionTask.action_type == action_type,
            ActionTask.status == TaskStatus.DISPATCHED,
        )
    )
    return int(value or 0)


def used_in_trailing_week(
    db: Session, account: LinkedInAccount, action_type: StepType, *, now: datetime | None = None
) -> int:
    today = local_day(account, now)
    value = db.scalar(
        select(func.coalesce(func.sum(DailyQuotaLedger.used), 0)).where(
            DailyQuotaLedger.linkedin_account_id == account.id,
            DailyQuotaLedger.action_type == action_type,
            DailyQuotaLedger.day >= today - timedelta(days=6),
            DailyQuotaLedger.day <= today,
        )
    )
    return int(value or 0)


def check(
    db: Session,
    account: LinkedInAccount,
    action_type: StepType,
    *,
    now: datetime | None = None,
) -> QuotaVerdict:
    """Whether one more action of this type is permitted right now."""
    if action_type not in BUDGETED:
        return QuotaVerdict(allowed=True)

    now = now or datetime.now(UTC)
    resolved = caps_mod.resolve(account, now=now)
    limit_today = int(getattr(resolved, BUDGETED[action_type]))

    # Committed plus in-flight: an action already handed to a worker has been
    # spent, even though LinkedIn has not answered yet.
    today = used_today(db, account, action_type, now=now) + in_flight(db, account, action_type)
    if today >= limit_today:
        return QuotaVerdict(
            allowed=False,
            reason=(
                f"daily {action_type.value} cap reached ({today}/{limit_today}, "
                f"{resolved.invite_limit_reason})"
                if action_type is StepType.INVITE
                else f"daily {action_type.value} cap reached ({today}/{limit_today})"
            ),
            used_today=today,
            limit_today=limit_today,
        )

    # The rolling weekly ceiling applies to invites only; it is the constraint
    # LinkedIn actually enforces on connection requests.
    if action_type is StepType.INVITE:
        week = used_in_trailing_week(db, account, action_type, now=now) + in_flight(
            db, account, action_type
        )
        if week >= resolved.weekly_invites:
            return QuotaVerdict(
                allowed=False,
                reason=(
                    f"trailing 7-day invite cap reached ({week}/{resolved.weekly_invites}) — "
                    "LinkedIn enforces a weekly ceiling regardless of daily pacing"
                ),
                used_today=today,
                limit_today=limit_today,
                used_this_week=week,
                limit_this_week=resolved.weekly_invites,
            )
        return QuotaVerdict(
            allowed=True,
            used_today=today,
            limit_today=limit_today,
            used_this_week=week,
            limit_this_week=resolved.weekly_invites,
        )

    return QuotaVerdict(allowed=True, used_today=today, limit_today=limit_today)


def consume(
    db: Session,
    account: LinkedInAccount,
    action_type: StepType,
    *,
    now: datetime | None = None,
    amount: int = 1,
) -> None:
    """Records a completed action. Called only after LinkedIn accepted it.

    An upsert rather than read-modify-write: two workers must never both read 4
    and both write 5.
    """
    if action_type not in BUDGETED:
        return

    day = local_day(account, now)
    stmt = (
        pg_insert(DailyQuotaLedger)
        .values(
            linkedin_account_id=account.id,
            day=day,
            action_type=action_type,
            used=amount,
        )
        .on_conflict_do_update(
            index_elements=["linkedin_account_id", "day", "action_type"],
            set_={"used": DailyQuotaLedger.used + amount},
        )
    )
    db.execute(stmt)


def halve_remaining_today(
    db: Session,
    account: LinkedInAccount,
    action_type: StepType,
    *,
    now: datetime | None = None,
) -> int:
    """Burns half of today's remaining budget after a soft limit.

    LinkedIn told us we are going too fast. Backing off in time is not enough —
    the volume has to come down too, or the same wall is hit again later today.
    Implemented by charging the ledger, so it survives a restart.
    """
    if action_type not in BUDGETED:
        return 0

    resolved = caps_mod.resolve(account, now=now)
    limit = int(getattr(resolved, BUDGETED[action_type]))
    used = used_today(db, account, action_type, now=now)
    remaining = max(0, limit - used)
    penalty = remaining // 2
    if penalty:
        consume(db, account, action_type, now=now, amount=penalty)
    return penalty


def summary(db: Session, account_id: uuid.UUID, *, days: int = 7) -> dict[str, int]:
    """Totals per action type over the last N days, for analytics tiles."""
    rows = db.execute(
        select(DailyQuotaLedger.action_type, func.sum(DailyQuotaLedger.used))
        .where(
            DailyQuotaLedger.linkedin_account_id == account_id,
            DailyQuotaLedger.day >= (datetime.now(UTC).date() - timedelta(days=days - 1)),
        )
        .group_by(DailyQuotaLedger.action_type)
    ).all()
    return {str(action_type): int(total or 0) for action_type, total in rows}
