"""Notification feed behind the bell icon."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import Workspace_
from app.models.tenancy import Notification
from app.schemas.notifications import NotificationPage, NotificationResponse
from app.services import notification_service

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["notifications"])


def _to_response(notification: Notification, read: bool) -> NotificationResponse:
    return NotificationResponse(
        id=notification.id,
        type=notification.type,
        title=notification.title,
        body=notification.body,
        link=notification.link,
        read=read,
        created_at=notification.created_at,
    )


@router.get("/notifications", response_model=NotificationPage)
async def list_notifications(
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NotificationPage:
    rows, total = await notification_service.list_for_workspace(db, ctx, limit=limit, offset=offset)
    unread = await notification_service.unread_count(db, ctx)
    return NotificationPage(
        items=[_to_response(n, read) for n, read in rows],
        total=total,
        unread_count=unread,
        limit=limit,
        offset=offset,
    )


@router.post("/notifications/{notification_id}/read", response_model=NotificationResponse)
async def mark_read(
    notification_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> NotificationResponse:
    notification = await notification_service.mark_read(db, ctx, notification_id)
    return _to_response(notification, True)


@router.post("/notifications/read-all")
async def mark_all_read(
    ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, int]:
    changed = await notification_service.mark_all_read(db, ctx)
    return {"marked_read": changed}
