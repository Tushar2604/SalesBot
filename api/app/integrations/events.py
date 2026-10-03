"""Webhook events: the catalog, and the outbox writer.

`emit()` / `emit_sync()` add one WebhookDelivery row per subscribed endpoint
to the caller's session, so an event is recorded exactly when the change it
describes commits, and never for a change that rolled back. The webhook
worker delivers the rows afterwards.

Every payload has the same envelope:

    {
      "id": "<event uuid, the same for every endpoint — dedupe on it>",
      "type": "reply.received",
      "created_at": "2026-09-28T10:15:00+00:00",
      "workspace_id": "<uuid>",
      "data": { ...event specific... }
    }
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.integrations import DeliveryStatus, WebhookDelivery, WebhookEndpoint

# type -> what it means. The API exposes this list; the UI builds its
# checkboxes from it.
CATALOG: dict[str, str] = {
    "lead.imported": "Leads were added to a list (CSV, pasted links, AI lead finder)",
    "campaign.status_changed": "A campaign was launched, paused, resumed or completed",
    "campaign.leads_enrolled": "Leads were added to a campaign",
    "profile.viewed": "A campaign visited a lead's profile",
    "invite.sent": "A connection request was sent",
    "invite.accepted": "A lead accepted a connection request",
    "message.sent": "A message was sent (campaign, inbox reply or AI assistant)",
    "reply.received": "A lead replied in the LinkedIn inbox",
    "conversation.labeled": "AI labelled a conversation (interested, not interested...)",
    "assistant.handoff": "The AI assistant handed a conversation to a person",
    "post.liked": "A post was liked (manually or by auto-like)",
    "post.published": "A Content Studio post went live",
    "account.needs_attention": "A LinkedIn account was paused, restricted or disconnected",
    "webhook.test": "A test event sent from the Integrations page",
}


def envelope(
    event_type: str, workspace_id: uuid.UUID, data: dict[str, Any], event_id: uuid.UUID
) -> dict[str, Any]:
    return {
        "id": str(event_id),
        "type": event_type,
        "created_at": datetime.now(UTC).isoformat(),
        "workspace_id": str(workspace_id),
        "data": data,
    }


def _subscribed(endpoint: WebhookEndpoint, event_type: str) -> bool:
    events = endpoint.events or []
    return "*" in events or event_type in events


def _endpoints_query(workspace_id: uuid.UUID):  # type: ignore[no-untyped-def]
    return select(WebhookEndpoint).where(
        WebhookEndpoint.workspace_id == workspace_id, WebhookEndpoint.enabled.is_(True)
    )


def _deliveries(
    endpoints: list[WebhookEndpoint],
    event_type: str,
    workspace_id: uuid.UUID,
    data: dict[str, Any],
) -> list[WebhookDelivery]:
    if event_type not in CATALOG:
        raise ValueError(f"unknown webhook event type {event_type!r}")
    targets = [e for e in endpoints if _subscribed(e, event_type)]
    if not targets:
        return []
    event_id = uuid.uuid4()
    payload = envelope(event_type, workspace_id, data, event_id)
    now = datetime.now(UTC)
    return [
        WebhookDelivery(
            workspace_id=workspace_id,
            endpoint_id=endpoint.id,
            event_id=event_id,
            event_type=event_type,
            payload=payload,
            status=DeliveryStatus.PENDING,
            next_attempt_at=now,
        )
        for endpoint in targets
    ]


def emit_sync(db: Session, workspace_id: uuid.UUID, event_type: str, data: dict[str, Any]) -> int:
    """Worker-side: queue `event_type` for every subscribed endpoint, in the
    caller's transaction. Returns how many deliveries were queued. Sending
    happens later in the webhook worker, so a slow or broken receiver can
    never hold up or fail the action that caused the event."""
    endpoints = list(db.execute(_endpoints_query(workspace_id)).scalars())
    rows = _deliveries(endpoints, event_type, workspace_id, data)
    db.add_all(rows)
    return len(rows)


async def emit(
    db: AsyncSession, workspace_id: uuid.UUID, event_type: str, data: dict[str, Any]
) -> int:
    """API-side variant of emit_sync."""
    endpoints = list((await db.execute(_endpoints_query(workspace_id))).scalars())
    rows = _deliveries(endpoints, event_type, workspace_id, data)
    db.add_all(rows)
    return len(rows)


# ── payload helpers, so every event describes things the same way ──────────


def lead_data(lead: Any) -> dict[str, Any] | None:
    if lead is None:
        return None
    return {
        "id": str(lead.id),
        "public_id": lead.public_id,
        "profile_url": lead.profile_url,
        "first_name": lead.first_name,
        "last_name": lead.last_name,
        "title": lead.title,
        "company": lead.company,
        "location": lead.location,
        "email": lead.email,
    }


def account_data(account: Any) -> dict[str, Any] | None:
    if account is None:
        return None
    return {
        "id": str(account.id),
        "label": account.label,
        "name": account.full_name,
    }
