"""Autonomous liking: a background sweep likes a small random handful of an
account's own cached feed posts each day, for accounts that opted in.

This stands in for a person deciding to like something while skimming their
feed. It is strictly a heuristic — real human judgement is safer than any
approximation of it — which is why it is opt-in (`LinkedInAccount.auto_like_enabled`)
and deliberately conservative:

  * 2-5 likes a day, drawn once per account per day (`caps.auto_like_daily_target`).
  * Only posts the user's topic rules allow (`like_rules`): any post, or only
    posts about chosen topics, and never posts about excluded ones.
  * Only considered during the account's own working hours, at a low chance per
    sweep tick, so the day's target is reached gradually rather than all at once.
  * Only picks posts already sitting in the feed cache — it never reads LinkedIn
    itself; that stays the job of the manual Refresh action.
  * Goes through the exact same `ActionTask` queue, pacing, quota and circuit
    breaker as a manually-clicked like or an invite. This sweep only ever
    decides *whether* to queue one more like; the dispatcher still decides
    *when* it actually runs.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db import session_scope
from app.linkedin import caps as caps_mod
from app.linkedin import like_rules
from app.models.campaigns import ActionTask, StepType, TaskStatus
from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus
from app.scheduler import pacing, quota
from app.services import audit
from app.worker.celery_app import celery_app

log = get_logger(__name__)

# Chance, per sweep tick, that an account under its daily target attempts to
# queue one more like. Kept low so 2-5 likes spread across a whole working
# day of ticks rather than clustering right after the target is drawn.
_ATTEMPT_CHANCE = 0.25
# A feed cache older than this is not fresh enough to like from; a refresh is
# queued instead and this tick likes nothing.
_STALE_FEED = timedelta(hours=4)


def _pending_like_urns(db: Session, account_id: Any) -> set[str]:
    rows = db.execute(
        select(ActionTask.payload).where(
            ActionTask.linkedin_account_id == account_id,
            ActionTask.action_type == StepType.LIKE_POST,
            ActionTask.status.in_((TaskStatus.PENDING, TaskStatus.DISPATCHED)),
        )
    ).scalars().all()
    return {str(payload.get("post_urn")) for payload in rows if payload.get("post_urn")}


def _queue_like(
    db: Session, account: LinkedInAccount, post_urn: str, *, now: datetime, matched_topic: str = ""
) -> None:
    scheduled_at = pacing.schedule_within_working_hours(account, now)
    local_day = now.astimezone(caps_mod.zone_for(account)).date()
    idempotency_key = ActionTask.build_like_idempotency_key(account.id, post_urn, local_day)

    exists = db.execute(
        select(ActionTask.id).where(ActionTask.idempotency_key == idempotency_key)
    ).scalar_one_or_none()
    if exists is not None:
        return

    db.add(
        ActionTask(
            workspace_id=account.workspace_id,
            linkedin_account_id=account.id,
            campaign_lead_id=None,
            step_id=None,
            action_type=StepType.LIKE_POST,
            payload={"post_urn": post_urn, "source": "auto", "matched_topic": matched_topic},
            scheduled_at=scheduled_at,
            status=TaskStatus.PENDING,
            idempotency_key=idempotency_key,
        )
    )
    audit.record_sync(
        db,
        "linkedin_account.like_queued_auto",
        workspace_id=account.workspace_id,
        target_type="linkedin_account",
        target_id=account.id,
        metadata={"post_urn": post_urn, "matched_topic": matched_topic},
    )


@celery_app.task(name="linkedin.action.consider_auto_like", bind=True, max_retries=0)
def consider_auto_like(self: Any, account_id: str) -> dict[str, Any]:
    _ = self
    now = datetime.now(UTC)

    with session_scope() as db:
        account = db.get(LinkedInAccount, account_id)
        if account is None or not account.auto_like_enabled:
            return {"status": "skipped"}
        if account.status is not LinkedInAccountStatus.ACTIVE or not account.is_connected:
            return {"status": "skipped"}

        in_hours, _ = caps_mod.within_working_hours(account, now=now)
        if not in_hours:
            return {"status": "outside_working_hours"}

        target = min(
            caps_mod.auto_like_daily_target(account, now=now),
            caps_mod.resolve(account, now=now).daily_likes,
        )
        already = quota.used_today(
            db, account, StepType.LIKE_POST, now=now
        ) + quota.in_flight(db, account, StepType.LIKE_POST)
        if already >= target:
            return {"status": "target_reached", "target": target, "already": already}

        if random.random() >= _ATTEMPT_CHANCE:  # noqa: S311 - pacing, not security
            return {"status": "skipped_this_tick"}

        if account.cached_feed_at is None or now - account.cached_feed_at > _STALE_FEED:
            celery_app.send_task(
                "linkedin.action.refresh_feed", args=[str(account.id)], queue="linkedin.action"
            )
            return {"status": "feed_stale_refreshing"}

        # The user's topic rules: judge the cached posts once per rule set
        # (keywords, or AI by meaning), and keep the verdicts on the cache.
        rules = like_rules.resolve(account.auto_like_rules)
        feed, changed = like_rules.judge_feed(list(account.cached_feed or []), rules)
        if changed:
            account.cached_feed = feed

        pending = _pending_like_urns(db, account.id)
        unliked = [
            post
            for post in feed
            if not post.get("liked") and str(post.get("urn")) not in pending
        ]
        if not unliked:
            return {"status": "no_candidates"}
        candidates = [p for p in unliked if (p.get("like_match") or {}).get("like")]
        if not candidates:
            return {"status": "no_matching_posts", "rules": rules.mode}

        chosen = random.choice(candidates)  # noqa: S311 - which post to like, not security
        topic = str((chosen.get("like_match") or {}).get("topic") or "")
        _queue_like(db, account, str(chosen["urn"]), now=now, matched_topic=topic)
        return {"status": "queued", "post_urn": chosen["urn"], "topic": topic}


@celery_app.task(name="linkedin.action.auto_like_sweep")
def auto_like_sweep() -> dict[str, int]:
    """Beat job: stagger a consider-tick across every opted-in account.

    Same staggering rationale as `sync.poll_all` — many accounts acting in the
    same second is a pattern regardless of per-account pacing.
    """
    with session_scope() as db:
        account_ids = (
            db.execute(
                select(LinkedInAccount.id).where(
                    LinkedInAccount.auto_like_enabled.is_(True),
                    LinkedInAccount.status == LinkedInAccountStatus.ACTIVE,
                )
            )
            .scalars()
            .all()
        )

    if not account_ids:
        return {"queued": 0}

    offsets = pacing.spread_start_times(len(account_ids), window_seconds=300)
    for account_id, offset in zip(account_ids, offsets, strict=True):
        consider_auto_like.apply_async(
            args=[str(account_id)], countdown=offset, queue="linkedin.action"
        )
    return {"queued": len(account_ids)}
