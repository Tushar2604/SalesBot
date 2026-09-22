"""Notification feed behind the bell icon.

Mirrors `app.services.audit`: an async `create` for API-side callers and a
sync `create_sync` for Celery tasks, which run on a plain `Session`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.errors import NotFoundError
from app.deps import WorkspaceContext
from app.models.tenancy import Notification, NotificationType


def _build(
    workspace_id: uuid.UUID, type_: NotificationType, title: str, *, body: str, link: str
) -> Notification:
    return Notification(workspace_id=workspace_id, type=type_, title=title, body=body, link=link)


async def create(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    type_: NotificationType,
    title: str,
    *,
    body: str = "",
    link: str = "",
) -> None:
    db.add(_build(workspace_id, type_, title, body=body, link=link))


def create_sync(
    db: Session,
    workspace_id: uuid.UUID,
    type_: NotificationType,
    title: str,
    *,
    body: str = "",
    link: str = "",
) -> None:
    """Worker-side variant — used by the sync poller and auth tasks."""
    db.add(_build(workspace_id, type_, title, body=body, link=link))


async def list_for_workspace(
    db: AsyncSession, ctx: WorkspaceContext, *, limit: int = 30, offset: int = 0
) -> tuple[list[tuple[Notification, bool]], int]:
    conditions = [Notification.workspace_id == ctx.workspace_id]
    count_stmt = select(func.count()).select_from(Notification).where(*conditions)
    total = (await db.scalar(count_stmt)) or 0

    rows = (
        (
            await db.execute(
                select(Notification)
                .where(*conditions)
                .order_by(desc(Notification.created_at))
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    user_id = str(ctx.user.id)
    return [(row, user_id in row.read_by) for row in rows], total


async def unread_count(db: AsyncSession, ctx: WorkspaceContext) -> int:
    rows = (
        (
            await db.execute(
                select(Notification.read_by).where(Notification.workspace_id == ctx.workspace_id)
            )
        )
        .scalars()
        .all()
    )
    user_id = str(ctx.user.id)
    return sum(1 for read_by in rows if user_id not in read_by)


async def _get(db: AsyncSession, ctx: WorkspaceContext, notification_id: uuid.UUID) -> Notification:
    notification = await db.get(Notification, notification_id)
    if notification is None or notification.workspace_id != ctx.workspace_id:
        raise NotFoundError("notification not found")
    return notification


async def mark_read(
    db: AsyncSession, ctx: WorkspaceContext, notification_id: uuid.UUID
) -> Notification:
    notification = await _get(db, ctx, notification_id)
    user_id = str(ctx.user.id)
    if user_id not in notification.read_by:
        # Reassign rather than mutate in place: JSONB column changes are only
        # detected by SQLAlchemy's unit of work when the attribute is set.
        notification.read_by = [*notification.read_by, user_id]
    return notification


async def mark_all_read(db: AsyncSession, ctx: WorkspaceContext) -> int:
    rows = (
        (
            await db.execute(
                select(Notification).where(Notification.workspace_id == ctx.workspace_id)
            )
        )
        .scalars()
        .all()
    )
    user_id = str(ctx.user.id)
    changed = 0
    for row in rows:
        if user_id not in row.read_by:
            row.read_by = [*row.read_by, user_id]
            changed += 1
    return changed
