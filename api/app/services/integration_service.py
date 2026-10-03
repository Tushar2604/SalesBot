"""API keys and webhook endpoints: create, list, change, remove."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.core.errors import NotFoundError, PermissionDeniedError, ValidationFailedError
from app.deps import WorkspaceContext
from app.integrations import api_keys, events, webhooks
from app.models.integrations import ApiKey, DeliveryStatus, WebhookDelivery, WebhookEndpoint
from app.models.tenancy import WorkspaceRole
from app.services import audit

MAX_KEYS = 25
MAX_ENDPOINTS = 20

# ── API keys ─────────────────────────────────────────────────────────────────


async def list_keys(db: AsyncSession, workspace_id: uuid.UUID) -> list[ApiKey]:
    rows = await db.execute(
        select(ApiKey).where(ApiKey.workspace_id == workspace_id).order_by(ApiKey.created_at.desc())
    )
    return list(rows.scalars())


async def create_key(
    db: AsyncSession, ctx: WorkspaceContext, name: str, role: WorkspaceRole
) -> tuple[ApiKey, str]:
    ctx.require_login()
    if role is WorkspaceRole.OWNER:
        raise ValidationFailedError("an API key can be a member or an admin, never an owner")
    if not ctx.role.can_act_as(role):
        raise PermissionDeniedError(
            f"you can't create a key with more access ({role.value}) than you have"
        )
    active = [k for k in await list_keys(db, ctx.workspace_id) if k.revoked_at is None]
    if len(active) >= MAX_KEYS:
        raise ValidationFailedError(f"a workspace can have at most {MAX_KEYS} active API keys")

    full, prefix, digest = api_keys.generate()
    key = ApiKey(
        workspace_id=ctx.workspace_id,
        created_by_id=ctx.user.id,
        name=name.strip()[:120] or "API key",
        prefix=prefix,
        key_hash=digest,
        role=role,
    )
    db.add(key)
    await db.flush()
    await audit.record(
        db,
        "integrations.api_key_created",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="api_key",
        target_id=key.id,
        metadata={"name": key.name, "role": role.value, "prefix": prefix},
    )
    await db.commit()
    await db.refresh(key)
    return key, full


async def revoke_key(db: AsyncSession, ctx: WorkspaceContext, key_id: uuid.UUID) -> ApiKey:
    ctx.require_login()
    key = await db.get(ApiKey, key_id)
    if key is None or key.workspace_id != ctx.workspace_id:
        raise NotFoundError("API key not found")
    if key.revoked_at is None:
        key.revoked_at = datetime.now(UTC)
        await audit.record(
            db,
            "integrations.api_key_revoked",
            workspace_id=ctx.workspace_id,
            actor_user_id=ctx.user.id,
            target_type="api_key",
            target_id=key.id,
            metadata={"name": key.name, "prefix": key.prefix},
        )
    await db.commit()
    await db.refresh(key)
    return key


# ── webhook endpoints ────────────────────────────────────────────────────────


def _check_events(names: list[str]) -> list[str]:
    cleaned = list(dict.fromkeys(n.strip() for n in names if n.strip()))
    if not cleaned:
        raise ValidationFailedError("choose at least one event, or * for all of them")
    unknown = [n for n in cleaned if n != "*" and n not in events.CATALOG]
    if unknown:
        raise ValidationFailedError(f"unknown event type(s): {', '.join(unknown)}")
    return ["*"] if "*" in cleaned else cleaned


def _check_url(url: str) -> str:
    try:
        return webhooks.check_url(url)
    except webhooks.UnsafeUrl as exc:
        raise ValidationFailedError(str(exc)) from exc


async def list_endpoints(db: AsyncSession, workspace_id: uuid.UUID) -> list[WebhookEndpoint]:
    rows = await db.execute(
        select(WebhookEndpoint)
        .where(WebhookEndpoint.workspace_id == workspace_id)
        .order_by(WebhookEndpoint.created_at.desc())
    )
    return list(rows.scalars())


async def get_endpoint(
    db: AsyncSession, workspace_id: uuid.UUID, endpoint_id: uuid.UUID
) -> WebhookEndpoint:
    endpoint = await db.get(WebhookEndpoint, endpoint_id)
    if endpoint is None or endpoint.workspace_id != workspace_id:
        raise NotFoundError("webhook not found")
    return endpoint


async def create_endpoint(
    db: AsyncSession, ctx: WorkspaceContext, url: str, description: str, event_types: list[str]
) -> tuple[WebhookEndpoint, str]:
    if len(await list_endpoints(db, ctx.workspace_id)) >= MAX_ENDPOINTS:
        raise ValidationFailedError(f"a workspace can have at most {MAX_ENDPOINTS} webhooks")
    secret = webhooks.new_secret()
    endpoint = WebhookEndpoint(
        workspace_id=ctx.workspace_id,
        created_by_id=ctx.user.id,
        url=_check_url(url),
        description=description.strip()[:200],
        events=_check_events(event_types),
        secret_ciphertext=crypto.encrypt_str(secret),
        enabled=True,
    )
    db.add(endpoint)
    await db.flush()
    await audit.record(
        db,
        "integrations.webhook_created",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="webhook_endpoint",
        target_id=endpoint.id,
        metadata={"url": endpoint.url, "events": endpoint.events, "via_api_key": ctx.via_api_key},
    )
    await db.commit()
    await db.refresh(endpoint)
    return endpoint, secret


async def update_endpoint(
    db: AsyncSession, ctx: WorkspaceContext, endpoint_id: uuid.UUID, patch: dict[str, Any]
) -> WebhookEndpoint:
    endpoint = await get_endpoint(db, ctx.workspace_id, endpoint_id)
    if patch.get("url") is not None:
        endpoint.url = _check_url(patch["url"])
    if patch.get("description") is not None:
        endpoint.description = str(patch["description"]).strip()[:200]
    if patch.get("events") is not None:
        endpoint.events = _check_events(patch["events"])
    if patch.get("enabled") is not None:
        endpoint.enabled = bool(patch["enabled"])
        if endpoint.enabled:
            # Switching it back on is a fresh start.
            endpoint.failure_streak = 0
            endpoint.disabled_reason = ""
    await db.commit()
    await db.refresh(endpoint)
    return endpoint


async def rotate_secret(
    db: AsyncSession, ctx: WorkspaceContext, endpoint_id: uuid.UUID
) -> tuple[WebhookEndpoint, str]:
    endpoint = await get_endpoint(db, ctx.workspace_id, endpoint_id)
    secret = webhooks.new_secret()
    endpoint.secret_ciphertext = crypto.encrypt_str(secret)
    await audit.record(
        db,
        "integrations.webhook_secret_rotated",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="webhook_endpoint",
        target_id=endpoint.id,
    )
    await db.commit()
    await db.refresh(endpoint)
    return endpoint, secret


async def delete_endpoint(db: AsyncSession, ctx: WorkspaceContext, endpoint_id: uuid.UUID) -> None:
    endpoint = await get_endpoint(db, ctx.workspace_id, endpoint_id)
    await audit.record(
        db,
        "integrations.webhook_deleted",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="webhook_endpoint",
        target_id=endpoint.id,
        metadata={"url": endpoint.url},
    )
    await db.delete(endpoint)
    await db.commit()


async def send_test(
    db: AsyncSession, ctx: WorkspaceContext, endpoint_id: uuid.UUID
) -> WebhookDelivery:
    """Queues a webhook.test event to this one endpoint (whatever it subscribes to)."""
    endpoint = await get_endpoint(db, ctx.workspace_id, endpoint_id)
    event_id = uuid.uuid4()
    delivery = WebhookDelivery(
        workspace_id=ctx.workspace_id,
        endpoint_id=endpoint.id,
        event_id=event_id,
        event_type="webhook.test",
        payload=events.envelope(
            "webhook.test",
            ctx.workspace_id,
            {"message": "Test event from SalesRobo. Your endpoint is connected."},
            event_id,
        ),
        status=DeliveryStatus.PENDING,
        next_attempt_at=datetime.now(UTC),
    )
    db.add(delivery)
    await db.commit()
    await db.refresh(delivery)
    return delivery


async def list_deliveries(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    endpoint_id: uuid.UUID | None = None,
    status: DeliveryStatus | None = None,
    limit: int = 50,
) -> list[WebhookDelivery]:
    query = select(WebhookDelivery).where(WebhookDelivery.workspace_id == workspace_id)
    if endpoint_id is not None:
        query = query.where(WebhookDelivery.endpoint_id == endpoint_id)
    if status is not None:
        query = query.where(WebhookDelivery.status == status)
    rows = await db.execute(query.order_by(WebhookDelivery.created_at.desc()).limit(limit))
    return list(rows.scalars())


async def retry_delivery(
    db: AsyncSession, ctx: WorkspaceContext, delivery_id: uuid.UUID
) -> WebhookDelivery:
    delivery = await db.get(WebhookDelivery, delivery_id)
    if delivery is None or delivery.workspace_id != ctx.workspace_id:
        raise NotFoundError("delivery not found")
    if delivery.status in (DeliveryStatus.PENDING, DeliveryStatus.SENDING):
        return delivery
    # A fresh set of attempts, same event id, so receivers still dedupe it.
    delivery.status = DeliveryStatus.PENDING
    delivery.attempts = 0
    delivery.next_attempt_at = datetime.now(UTC)
    delivery.error = ""
    await db.commit()
    await db.refresh(delivery)
    return delivery
