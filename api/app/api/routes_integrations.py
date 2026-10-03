"""Integration layer endpoints: API keys, webhooks and their delivery log.

Creating or revoking API keys needs a signed-in admin (a leaked key must not
be able to mint more). Webhooks can also be managed with an admin API key, so
tools like Zapier or n8n can subscribe and unsubscribe themselves.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import Workspace_
from app.integrations import events
from app.models.integrations import ApiKey, DeliveryStatus
from app.models.tenancy import WorkspaceRole
from app.schemas.integrations import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyResponse,
    DeliveryResponse,
    EventType,
    WebhookCreate,
    WebhookCreated,
    WebhookResponse,
    WebhookUpdate,
    WhoAmI,
)
from app.services import integration_service

router = APIRouter(prefix="/workspaces/{workspace_id}/integrations", tags=["integrations"])

Db = Annotated[AsyncSession, Depends(get_db)]


@router.get("/whoami", response_model=WhoAmI)
async def whoami(ctx: Workspace_, db: Db) -> WhoAmI:
    """Test a key: which workspace it opens, and with what role."""
    key = await db.get(ApiKey, ctx.api_key_id) if ctx.api_key_id else None
    return WhoAmI(
        workspace_id=ctx.workspace_id,
        workspace_name=ctx.workspace.name,
        role=ctx.role.value,
        via_api_key=ctx.via_api_key,
        api_key_name=key.name if key else "",
    )


@router.get("/events", response_model=list[EventType])
async def list_events(ctx: Workspace_) -> list[EventType]:
    _ = ctx
    return [EventType(type=t, description=d) for t, d in events.CATALOG.items()]


# ── API keys ─────────────────────────────────────────────────────────────────


@router.get("/api-keys", response_model=list[ApiKeyResponse])
async def list_api_keys(ctx: Workspace_, db: Db) -> list[ApiKeyResponse]:
    ctx.require_role(WorkspaceRole.ADMIN)
    return [
        ApiKeyResponse.model_validate(k)
        for k in await integration_service.list_keys(db, ctx.workspace_id)
    ]


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(payload: ApiKeyCreate, ctx: Workspace_, db: Db) -> ApiKeyCreated:
    ctx.require_role(WorkspaceRole.ADMIN)
    key, secret = await integration_service.create_key(
        db, ctx, payload.name, WorkspaceRole(payload.role)
    )
    return ApiKeyCreated(key=ApiKeyResponse.model_validate(key), secret=secret)


@router.delete("/api-keys/{key_id}", response_model=ApiKeyResponse)
async def revoke_api_key(key_id: uuid.UUID, ctx: Workspace_, db: Db) -> ApiKeyResponse:
    ctx.require_role(WorkspaceRole.ADMIN)
    return ApiKeyResponse.model_validate(await integration_service.revoke_key(db, ctx, key_id))


# ── webhooks ─────────────────────────────────────────────────────────────────


@router.get("/webhooks", response_model=list[WebhookResponse])
async def list_webhooks(ctx: Workspace_, db: Db) -> list[WebhookResponse]:
    ctx.require_role(WorkspaceRole.ADMIN)
    return [
        WebhookResponse.model_validate(e)
        for e in await integration_service.list_endpoints(db, ctx.workspace_id)
    ]


@router.post("/webhooks", response_model=WebhookCreated, status_code=status.HTTP_201_CREATED)
async def create_webhook(payload: WebhookCreate, ctx: Workspace_, db: Db) -> WebhookCreated:
    ctx.require_role(WorkspaceRole.ADMIN)
    endpoint, secret = await integration_service.create_endpoint(
        db, ctx, payload.url, payload.description, payload.events
    )
    return WebhookCreated(webhook=WebhookResponse.model_validate(endpoint), secret=secret)


@router.patch("/webhooks/{webhook_id}", response_model=WebhookResponse)
async def update_webhook(
    webhook_id: uuid.UUID, payload: WebhookUpdate, ctx: Workspace_, db: Db
) -> WebhookResponse:
    ctx.require_role(WorkspaceRole.ADMIN)
    endpoint = await integration_service.update_endpoint(
        db, ctx, webhook_id, payload.model_dump(exclude_none=True)
    )
    return WebhookResponse.model_validate(endpoint)


@router.delete("/webhooks/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook(webhook_id: uuid.UUID, ctx: Workspace_, db: Db) -> None:
    ctx.require_role(WorkspaceRole.ADMIN)
    await integration_service.delete_endpoint(db, ctx, webhook_id)


@router.post("/webhooks/{webhook_id}/rotate-secret", response_model=WebhookCreated)
async def rotate_webhook_secret(webhook_id: uuid.UUID, ctx: Workspace_, db: Db) -> WebhookCreated:
    ctx.require_role(WorkspaceRole.ADMIN)
    endpoint, secret = await integration_service.rotate_secret(db, ctx, webhook_id)
    return WebhookCreated(webhook=WebhookResponse.model_validate(endpoint), secret=secret)


@router.post(
    "/webhooks/{webhook_id}/test",
    response_model=DeliveryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def test_webhook(webhook_id: uuid.UUID, ctx: Workspace_, db: Db) -> DeliveryResponse:
    """Queues a webhook.test event; it arrives within ~15 seconds."""
    ctx.require_role(WorkspaceRole.ADMIN)
    return DeliveryResponse.model_validate(await integration_service.send_test(db, ctx, webhook_id))


@router.get("/deliveries", response_model=list[DeliveryResponse])
async def list_deliveries(
    ctx: Workspace_,
    db: Db,
    webhook_id: uuid.UUID | None = None,
    status_filter: Annotated[DeliveryStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[DeliveryResponse]:
    ctx.require_role(WorkspaceRole.ADMIN)
    rows = await integration_service.list_deliveries(
        db, ctx.workspace_id, endpoint_id=webhook_id, status=status_filter, limit=limit
    )
    return [DeliveryResponse.model_validate(r) for r in rows]


@router.post("/deliveries/{delivery_id}/retry", response_model=DeliveryResponse)
async def retry_delivery(delivery_id: uuid.UUID, ctx: Workspace_, db: Db) -> DeliveryResponse:
    ctx.require_role(WorkspaceRole.ADMIN)
    return DeliveryResponse.model_validate(
        await integration_service.retry_delivery(db, ctx, delivery_id)
    )
