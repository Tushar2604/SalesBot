"""Feed refresh: fetches the account's own feed and caches it for the UI.

Deliberately not a read done inline on the API request: it still needs the
account's single execution slot (the driver session is not thread-safe and must
never race a queued action), and a real page load takes seconds — too slow for
a synchronous HTTP handler. The API triggers this task and returns immediately;
the frontend reads the cached result from `LinkedInAccount.cached_feed`.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from app.core.logging import get_logger
from app.db import session_scope
from app.linkedin import build_driver, health
from app.models.linkedin import LinkedInAccount
from app.scheduler import dispatcher, locks, pacing
from app.worker.celery_app import celery_app

log = get_logger(__name__)

# How many posts a manual refresh pulls in. A person scrolling their own feed
# reads a screenful at a time, not fifty posts at once.
FEED_PAGE_SIZE = 15


def _post_to_cache_row(post: Any) -> dict[str, Any]:
    row = asdict(post)
    row.pop("raw", None)
    row.pop("posted_at", None)
    return row


@celery_app.task(name="linkedin.action.refresh_feed", bind=True, max_retries=0)
def refresh_feed(self: Any, account_id: str) -> dict[str, str]:
    _ = self
    now = datetime.now(UTC)

    with session_scope() as db:
        account = db.get(LinkedInAccount, account_id)
        if account is None:
            return {"status": "missing"}

        allowed, reason = health.can_dispatch(account, now=now)
        if not allowed:
            log.info("feed.refresh.blocked", account_id=account_id, reason=reason)
            return {"status": "blocked", "reason": reason}

        try:
            with locks.account_slot(account.id):
                driver = build_driver(account)
                try:
                    classification = None
                    if account.last_action_at is None or (
                        now - account.last_action_at
                    ).total_seconds() > 7200:
                        warm = driver.warm_session()
                        if warm.response_class.opens_circuit:
                            classification, posts = warm, []
                    if classification is None:
                        classification, posts = driver.get_feed(count=FEED_PAGE_SIZE)
                finally:
                    driver.close()
        except locks.SlotBusy:
            return {"status": "busy"}

        outcome = health.apply_classification(account, classification, now=now)
        if outcome.circuit_opened:
            dispatcher.pause_account_work(db, account.id, outcome.detail or "circuit opened")
            return {"status": "failed", "reason": outcome.detail}

        if not classification.ok:
            log.info(
                "feed.refresh.failed",
                account_id=account_id,
                classification=classification.response_class.value,
            )
            return {"status": "failed", "reason": classification.detail}

        account.cached_feed = [_post_to_cache_row(p) for p in posts]
        account.cached_feed_at = now
        account.last_action_at = now
        # Reading the feed still occupied the account's one execution slot and
        # looked like a real page load; the next action (a queued like, an
        # invite) is spaced out from it exactly as it would be from any other.
        account.next_allowed_at = pacing.next_allowed_at(now)
        return {"status": "ok", "count": str(len(posts))}
