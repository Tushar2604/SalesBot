"""Webhook delivery: the outbox sweep and the per-delivery send.

    webhooks.deliver_due   beat, every 15 s: claims due deliveries (SKIP LOCKED,
                           so two beats never double-send) and hands each to
    webhooks.deliver       one HTTP POST, then success / retry / give up

Retries back off 1m, 5m, 30m, 2h, 6h, 12h — seven attempts over about a day —
then the delivery is marked failed and can be re-sent from the Integrations
page. An endpoint that keeps failing is switched off rather than retried
forever, and says why.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core import crypto
from app.core.logging import get_logger
from app.db import session_scope
from app.integrations import webhooks
from app.models.integrations import DeliveryStatus, WebhookDelivery, WebhookEndpoint
from app.worker.celery_app import celery_app

log = get_logger(__name__)

BACKOFF = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=6),
    timedelta(hours=12),
)
MAX_ATTEMPTS = len(BACKOFF) + 1
# Failed attempts in a row (across deliveries) before the endpoint is switched off.
DISABLE_AFTER_STREAK = 50
# A send that never reported back is retried after this long.
_STUCK_AFTER = timedelta(minutes=10)
_KEEP_FOR = timedelta(days=30)
_BATCH = 200


def _claim_due(db: Session, now: datetime) -> list[uuid.UUID]:
    rows = list(
        db.execute(
            select(WebhookDelivery)
            .where(
                WebhookDelivery.status == DeliveryStatus.PENDING,
                WebhookDelivery.next_attempt_at <= now,
            )
            .order_by(WebhookDelivery.next_attempt_at)
            .limit(_BATCH)
            .with_for_update(skip_locked=True)
        ).scalars()
    )
    for row in rows:
        row.status = DeliveryStatus.SENDING
        row.sending_since = now
    return [row.id for row in rows]


@celery_app.task(name="webhooks.deliver_due")
def deliver_due() -> dict[str, int]:
    now = datetime.now(UTC)
    with session_scope() as db:
        # A worker that died mid-send leaves a row in SENDING; put it back.
        revived = db.execute(
            update(WebhookDelivery)
            .where(
                WebhookDelivery.status == DeliveryStatus.SENDING,
                WebhookDelivery.sending_since < now - _STUCK_AFTER,
            )
            .values(status=DeliveryStatus.PENDING, next_attempt_at=now)
        ).rowcount  # type: ignore[attr-defined]
        pruned = db.execute(
            delete(WebhookDelivery).where(WebhookDelivery.created_at < now - _KEEP_FOR)
        ).rowcount  # type: ignore[attr-defined]
        claimed = _claim_due(db, now)
    # After commit, so each task finds its row in SENDING.
    for delivery_id in claimed:
        deliver.apply_async(args=[str(delivery_id)], queue="webhooks")
    return {"claimed": len(claimed), "revived": revived or 0, "pruned": pruned or 0}


def run_delivery(db: Session, delivery: WebhookDelivery, *, transport: Any = None) -> str:
    """Sends one delivery and records the outcome. Returns the new status."""
    now = datetime.now(UTC)
    endpoint = db.get(WebhookEndpoint, delivery.endpoint_id)
    if endpoint is None:
        delivery.status = DeliveryStatus.FAILED
        delivery.error = "the endpoint was deleted"
        return delivery.status.value
    if not endpoint.enabled:
        delivery.status = DeliveryStatus.FAILED
        delivery.error = "the endpoint is switched off"
        return delivery.status.value

    delivery.attempts += 1
    result = webhooks.send(
        endpoint.url,
        crypto.decrypt_str(endpoint.secret_ciphertext),
        delivery.payload,
        delivery_id=str(delivery.id),
        attempt=delivery.attempts,
        transport=transport,
    )
    delivery.response_status = result.status
    delivery.response_body = result.body
    delivery.error = result.error[:500]
    delivery.duration_ms = result.duration_ms
    delivery.sending_since = None

    if result.ok:
        delivery.status = DeliveryStatus.SUCCEEDED
        delivery.delivered_at = now
        delivery.next_attempt_at = None
        endpoint.failure_streak = 0
        endpoint.last_success_at = now
        return delivery.status.value

    endpoint.failure_streak += 1
    endpoint.last_failure_at = now
    if endpoint.failure_streak >= DISABLE_AFTER_STREAK:
        endpoint.enabled = False
        endpoint.disabled_reason = (
            f"Switched off after {endpoint.failure_streak} failed attempts in a row "
            f"(last: {result.error or result.status})."
        )[:300]
        log.warning("webhooks.endpoint_disabled", endpoint_id=str(endpoint.id))

    if delivery.attempts >= MAX_ATTEMPTS or not endpoint.enabled:
        delivery.status = DeliveryStatus.FAILED
        delivery.next_attempt_at = None
    else:
        delivery.status = DeliveryStatus.PENDING
        delivery.next_attempt_at = now + BACKOFF[delivery.attempts - 1]
    log.info(
        "webhooks.delivery_failed",
        delivery_id=str(delivery.id),
        attempt=delivery.attempts,
        error=result.error,
        final=delivery.status is DeliveryStatus.FAILED,
    )
    return delivery.status.value


@celery_app.task(name="webhooks.deliver", bind=True, max_retries=0)
def deliver(self: Any, delivery_id: str) -> dict[str, str]:
    _ = self
    with session_scope() as db:
        delivery = db.get(WebhookDelivery, uuid.UUID(delivery_id), with_for_update=True)
        if delivery is None or delivery.status is not DeliveryStatus.SENDING:
            return {"status": "skipped"}
        return {"status": run_delivery(db, delivery)}
