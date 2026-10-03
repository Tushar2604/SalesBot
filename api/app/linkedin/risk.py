"""The ban-risk policy: what counts as unsafe, and the warning ("strike") system.

Two halves, one module, so the numbers a person is warned about and the numbers
the system enforces can never drift apart:

* **Risky settings.** `*_risks()` describe every way a requested setting leaves
  the safe policy. Services call `require_acknowledgement`, which refuses the
  change (HTTP 409, `risk_confirmation_required`) unless the person explicitly
  accepted those exact risks. Accepting one is itself a strike on the account.

* **Strikes.** Each LinkedIn push-back (a soft limit, a rate limit, a security
  check, a restriction) and each accepted override is an `AccountRiskEvent`.
  At `STRIKE_LIMIT` strikes inside `STRIKE_WINDOW`, the account is paused
  automatically and the workspace is told — before LinkedIn escalates on its own.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, object_session

from app.core.errors import RiskConfirmationRequired
from app.core.logging import get_logger
from app.linkedin.classify import ResponseClass
from app.models.linkedin import AccountRiskEvent, LinkedInAccount, LinkedInAccountStatus

log = get_logger(__name__)

STRIKE_LIMIT = 3
STRIKE_WINDOW = timedelta(days=30)

# ── the safe policy ──────────────────────────────────────────────────────────
# Well inside what LinkedIn tolerates for a warmed-up personal account; the
# hard ceilings in caps.py stay the absolute maximum on top of these.
SAFE_DAILY_INVITES = 25
SAFE_DAILY_MESSAGES = 40
SAFE_DAILY_VIEWS = 80
SAFE_WEEKLY_INVITES = 100
SAFE_WORKDAY_HOURS = 10
SAFE_MIN_STEP_WAIT_MINUTES = 30
SAFE_REPLY_DELAY_MIN_MINUTES = 2
SAFE_REPLIES_PER_THREAD = 3
SAFE_REPLIES_PER_ACCOUNT = 20


@dataclass(slots=True, frozen=True)
class Risk:
    key: str
    title: str
    detail: str


def _hours_between(start: str, end: str) -> float:
    try:
        sh, sm = (int(x) for x in start.split(":"))
        eh, em = (int(x) for x in end.split(":"))
    except (ValueError, AttributeError):
        return 0
    return (eh * 60 + em - sh * 60 - sm) / 60


def caps_risks(
    requested: dict[str, Any],
    *,
    test_mode: bool | None,
    account_age_days: int,
    auto_like_enabled: bool | None = None,
) -> list[Risk]:
    """Risks in a requested change to an account's limits and schedule."""
    risks: list[Risk] = []
    invites = requested.get("daily_invites")
    if invites is not None and invites > SAFE_DAILY_INVITES:
        risks.append(
            Risk(
                "daily_invites",
                f"{invites} connection requests a day",
                f"More than {SAFE_DAILY_INVITES} invites a day is the most common reason LinkedIn "
                "restricts an account.",
            )
        )
    messages = requested.get("daily_messages")
    if messages is not None and messages > SAFE_DAILY_MESSAGES:
        risks.append(
            Risk(
                "daily_messages",
                f"{messages} messages a day",
                f"Above {SAFE_DAILY_MESSAGES} messages a day reads as bulk messaging and gets reported.",
            )
        )
    views = requested.get("daily_views")
    if views is not None and views > SAFE_DAILY_VIEWS:
        risks.append(
            Risk(
                "daily_views",
                f"{views} profile views a day",
                f"Above {SAFE_DAILY_VIEWS} views a day looks like scraping.",
            )
        )
    weekly = requested.get("weekly_invites")
    if weekly is not None and weekly > SAFE_WEEKLY_INVITES:
        risks.append(
            Risk(
                "weekly_invites",
                f"{weekly} invites a week",
                f"LinkedIn enforces roughly {SAFE_WEEKLY_INVITES} invites a week and restricts above it.",
            )
        )
    hours = requested.get("working_hours")
    if hours and _hours_between(hours.get("start", ""), hours.get("end", "")) > SAFE_WORKDAY_HOURS:
        risks.append(
            Risk(
                "working_hours",
                "A working day longer than 10 hours",
                "Activity from early morning to late night, every day, is not how people use LinkedIn.",
            )
        )
    if requested.get("weekdays_only") is False:
        risks.append(
            Risk(
                "weekends",
                "Sending on weekends",
                "Seven-day-a-week activity is a strong automation signal.",
            )
        )
    if test_mode is False and account_age_days < 7:
        risks.append(
            Risk(
                "test_mode_early",
                "Leaving test mode in the first week",
                "A newly connected account should stay at warm-up volume for its first 7 days.",
            )
        )
    if auto_like_enabled:
        risks.append(
            Risk(
                "auto_like_enabled",
                "Letting the system like posts on its own",
                "It picks 2-5 posts a day at random from the cached feed, on the same pacing "
                "and caps as a manual like — but it is a heuristic standing in for a person's "
                "judgement, not the real thing. Prefer clicking Like yourself when you can.",
            )
        )
    return risks


def step_risks(steps: list[dict[str, Any]]) -> list[Risk]:
    """Risks in a campaign's step timing."""
    risks: list[Risk] = []
    for index, step in enumerate(steps, start=1):
        timing = step.get("timing", "smart")
        if timing == "asap":
            risks.append(
                Risk(
                    f"step_{index}_asap",
                    f"Step {index} set to ASAP",
                    "ASAP fires the moment limits allow, without a natural delay. Bursts of "
                    "instant actions are exactly what LinkedIn's automation detection looks for.",
                )
            )
        elif timing == "delay":
            minutes = step.get("delay_minutes") or 0
            if index > 1 and minutes < SAFE_MIN_STEP_WAIT_MINUTES:
                risks.append(
                    Risk(
                        f"step_{index}_short_wait",
                        f"Step {index} waits only {minutes} minutes",
                        f"Following up in under {SAFE_MIN_STEP_WAIT_MINUTES} minutes looks automated "
                        "to the person and to LinkedIn.",
                    )
                )
    return risks


def assistant_risks(settings: dict[str, Any]) -> list[Risk]:
    """Risks in the AI assistant's settings (only matter when it sends by itself)."""
    if settings.get("mode") != "auto":
        return []
    risks: list[Risk] = []
    if settings.get("reply_delay_min_minutes", 0) < SAFE_REPLY_DELAY_MIN_MINUTES:
        risks.append(
            Risk(
                "reply_delay",
                "Replies faster than 2 minutes",
                "Instant replies, around the clock, are the clearest sign of a bot.",
            )
        )
    if not settings.get("working_hours_only", True):
        risks.append(
            Risk(
                "reply_after_hours",
                "Replying outside working hours",
                "Answering at 3am every night is not human behaviour.",
            )
        )
    if settings.get("max_replies_per_thread_per_day", 0) > SAFE_REPLIES_PER_THREAD:
        risks.append(
            Risk(
                "thread_replies",
                "More than 3 automatic replies per conversation a day",
                "Long rapid back-and-forths are where people notice they are talking to software.",
            )
        )
    if settings.get("max_replies_per_account_per_day", 0) > SAFE_REPLIES_PER_ACCOUNT:
        risks.append(
            Risk(
                "account_replies",
                "More than 20 automatic replies a day",
                "High automatic reply volume adds to the account's daily message footprint.",
            )
        )
    return risks


def resume_risks(strikes: int) -> list[Risk]:
    if strikes < STRIKE_LIMIT:
        return []
    return [
        Risk(
            "resume_flagged",
            f"This account has {strikes} warnings",
            "It was paused because LinkedIn is already pushing back. Resuming now is the most "
            "likely way to turn a warning into a restriction. Waiting a few days is safer.",
        )
    ]


def require_acknowledgement(risks: list[Risk], acknowledged: bool) -> None:
    """Refuses unacknowledged risky changes. The 409 carries the risks to show."""
    if risks and not acknowledged:
        raise RiskConfirmationRequired(
            "This change can get the LinkedIn account restricted or banned.",
            details={"risks": [asdict(r) for r in risks]},
        )


# ── strikes ──────────────────────────────────────────────────────────────────

# LinkedIn's own push-back, weighted by how close it is to a restriction.
LINKEDIN_STRIKES: dict[ResponseClass, tuple[int, str]] = {
    ResponseClass.SOFT_LIMIT: (1, "LinkedIn soft limit (weekly invite limit or similar)"),
    ResponseClass.RATE_LIMITED: (1, "LinkedIn rate-limited the account"),
    ResponseClass.CHALLENGE: (2, "LinkedIn asked for a security check"),
    ResponseClass.BLOCKED: (3, "LinkedIn restricted the account"),
}


def risk_level(strikes: int) -> str:
    """ "safe" | "watch" | "at_risk" | "critical" — shown next to the x/3 count."""
    if strikes >= STRIKE_LIMIT:
        return "critical"
    if strikes == 2:
        return "at_risk"
    if strikes == 1:
        return "watch"
    return "safe"


def _window_start(now: datetime) -> datetime:
    return now - STRIKE_WINDOW


def _strikes_query(account_ids: list[uuid.UUID], now: datetime):  # type: ignore[no-untyped-def]
    return (
        select(
            AccountRiskEvent.linkedin_account_id,
            func.coalesce(func.sum(AccountRiskEvent.strikes), 0),
        )
        .where(
            AccountRiskEvent.linkedin_account_id.in_(account_ids),
            AccountRiskEvent.created_at >= _window_start(now),
            AccountRiskEvent.cleared_at.is_(None),
        )
        .group_by(AccountRiskEvent.linkedin_account_id)
    )


def strikes_sync(db: Session, account_id: uuid.UUID, *, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    row = db.execute(_strikes_query([account_id], now)).first()
    return int(row[1]) if row else 0


async def strikes_by_account(
    db: AsyncSession, account_ids: list[uuid.UUID], *, now: datetime | None = None
) -> dict[uuid.UUID, int]:
    if not account_ids:
        return {}
    now = now or datetime.now(UTC)
    rows = (await db.execute(_strikes_query(account_ids, now))).all()
    return {account_id: int(total) for account_id, total in rows}


def _event(
    account: LinkedInAccount,
    *,
    source: str,
    kind: str,
    strikes: int,
    detail: str,
    actor_user_id: uuid.UUID | None,
) -> AccountRiskEvent:
    return AccountRiskEvent(
        linkedin_account_id=account.id,
        workspace_id=account.workspace_id,
        source=source,
        kind=kind[:60],
        strikes=strikes,
        detail=detail[:500],
        actor_user_id=actor_user_id,
    )


def _auto_pause(account: LinkedInAccount, strikes: int) -> bool:
    """Pauses an active account that just reached the limit. True if it did."""
    if strikes < STRIKE_LIMIT or account.status is not LinkedInAccountStatus.ACTIVE:
        return False
    account.status = LinkedInAccountStatus.PAUSED
    account.status_detail = (
        f"Paused automatically: {strikes} safety warnings in the last 30 days. "
        "Resuming needs confirmation."
    )
    log.warning("linkedin.risk.auto_paused", account_id=str(account.id), strikes=strikes)
    return True


def _notify_sync(db: Session, account: LinkedInAccount, title: str, body: str) -> None:
    from app.models.tenancy import NotificationType
    from app.services import notification_service

    notification_service.create_sync(
        db,
        account.workspace_id,
        NotificationType.ACCOUNT_RISK,
        title,
        body=body[:400],
        link="/accounts",
    )


def record_linkedin_signal(
    account: LinkedInAccount, response_class: ResponseClass, detail: str
) -> None:
    """Called from health.apply_classification, inside whatever sync session owns
    the account. Adds the warning, and pauses the account at the limit."""
    weight = LINKEDIN_STRIKES.get(response_class)
    db = object_session(account)
    if weight is None or not isinstance(db, Session):
        return
    strikes, label = weight
    db.add(
        _event(
            account,
            source="linkedin",
            kind=response_class.value,
            strikes=strikes,
            detail=f"{label}. {detail}".strip(),
            actor_user_id=None,
        )
    )
    db.flush()
    total = strikes_sync(db, account.id)
    name = account.full_name or account.label or "A LinkedIn account"
    if _auto_pause(account, total):
        _notify_sync(
            db,
            account,
            f"{name} was paused to protect it",
            f"{total} safety warnings in 30 days. Latest: {label}.",
        )
    else:
        _notify_sync(
            db,
            account,
            f"Safety warning on {name} ({min(total, STRIKE_LIMIT)}/{STRIKE_LIMIT})",
            label,
        )


def record_error_streak(account: LinkedInAccount, detail: str) -> None:
    db = object_session(account)
    if not isinstance(db, Session):
        return
    db.add(
        _event(
            account,
            source="linkedin",
            kind="error_streak",
            strikes=1,
            detail=detail,
            actor_user_id=None,
        )
    )
    db.flush()
    _auto_pause(account, strikes_sync(db, account.id))


async def record_overrides(
    db: AsyncSession,
    accounts: list[LinkedInAccount],
    risks: list[Risk],
    actor_user_id: uuid.UUID,
) -> None:
    """One strike per account for accepting risks, whatever their number: the
    count measures how often someone overrode the policy, not how many fields."""
    if not risks:
        return
    summary = "; ".join(r.title for r in risks)
    for account in accounts:
        db.add(
            _event(
                account,
                source="override",
                kind="risky_setting_accepted",
                strikes=1,
                detail=f"Accepted: {summary}",
                actor_user_id=actor_user_id,
            )
        )
    await db.flush()
    totals = await strikes_by_account(db, [a.id for a in accounts])
    for account in accounts:
        _auto_pause(account, totals.get(account.id, 0))
