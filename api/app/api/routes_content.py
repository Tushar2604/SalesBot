"""Content Studio endpoints: posts, media, templates, calendar, queue, AI.

Thin handlers, as everywhere else in this API — validation and persistence live
in `content_service`, storage in `media_service`, LinkedIn in the worker.

Every route is mounted under `/workspaces/{workspace_id}` and depends on
`Workspace_`, so membership is proven before a handler runs and no handler ever
filters by a workspace id taken from the request body.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import content as ai_content
from app.core.errors import NotFoundError, ValidationFailedError
from app.db import get_db
from app.deps import Workspace_
from app.models.content import PostStatus
from app.models.tenancy import WorkspaceRole
from app.schemas.content import (
    AiGenerateRequest,
    AiImproveRequest,
    AiResponse,
    ApprovalSettingsRequest,
    ApprovalSettingsResponse,
    CalendarResponse,
    MediaAssetResponse,
    MediaLimitsResponse,
    PostCreateRequest,
    PostPage,
    PostResponse,
    PostUpdateRequest,
    QueueAddRequest,
    QueueMoveRequest,
    QueueResponse,
    QueueSlot,
    QueueUpdateRequest,
    ReviewRequest,
    ScheduleRequest,
    TemplateCreateRequest,
    TemplateResponse,
    TemplateUpdateRequest,
)
from app.services import content_service, media_service
from app.worker.celery_app import celery_app

router = APIRouter(prefix="/workspaces/{workspace_id}/content", tags=["content"])


# ── posts ────────────────────────────────────────────────────────────────────


@router.get("/posts", response_model=PostPage)
async def list_posts(
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
    status_filter: Annotated[list[PostStatus] | None, Query(alias="status")] = None,
    account_id: uuid.UUID | None = None,
    author_id: uuid.UUID | None = None,
    search: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> PostPage:
    posts, total = await content_service.list_posts(
        db,
        ctx.workspace_id,
        statuses=status_filter,
        account_id=account_id,
        author_id=author_id,
        search=search,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
        offset=offset,
    )
    presentation = await content_service.build_presentation(db, posts)
    return PostPage(
        items=[content_service.to_response(post, presentation) for post in posts],
        total=total,
        limit=limit,
        offset=offset,
        counts=await content_service.status_counts(db, ctx.workspace_id),
    )


@router.post("/posts", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
async def create_post(
    payload: PostCreateRequest, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> PostResponse:
    """Creates a draft. Nothing is scheduled or sent by this call."""
    ctx.require_role(WorkspaceRole.MEMBER)
    post = await content_service.create_post(db, ctx, payload)
    return await content_service.respond(db, post)


@router.get("/posts/{post_id}", response_model=PostResponse)
async def get_post(
    post_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> PostResponse:
    post = await content_service.get_post(db, ctx.workspace_id, post_id)
    return await content_service.respond(db, post)


@router.patch("/posts/{post_id}", response_model=PostResponse)
async def update_post(
    post_id: uuid.UUID,
    payload: PostUpdateRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PostResponse:
    """Also the autosave endpoint — the composer PATCHes this as the user types."""
    post = await content_service.get_post(db, ctx.workspace_id, post_id)
    post = await content_service.update_post(db, ctx, post, payload)
    return await content_service.respond(db, post)


@router.delete("/posts/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    post_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> None:
    post = await content_service.get_post(db, ctx.workspace_id, post_id)
    await content_service.delete_post(db, ctx, post)


@router.post("/posts/{post_id}/duplicate", response_model=PostResponse, status_code=201)
async def duplicate_post(
    post_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> PostResponse:
    ctx.require_role(WorkspaceRole.MEMBER)
    post = await content_service.get_post(db, ctx.workspace_id, post_id)
    copy = await content_service.duplicate_post(db, ctx, post)
    return await content_service.respond(db, copy)


@router.post("/posts/{post_id}/repurpose", response_model=PostResponse, status_code=201)
async def repurpose_post(
    post_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> PostResponse:
    """AI-rewrites an existing post into a new draft. Never publishes it."""
    ctx.require_role(WorkspaceRole.MEMBER)
    post = await content_service.get_post(db, ctx.workspace_id, post_id)
    if not post.content.strip():
        raise ValidationFailedError("there is no text to repurpose")

    variants, _ = await anyio.to_thread.run_sync(ai_content.improve, post.content, "repurpose")
    copy = await content_service.duplicate_post(db, ctx, post, content=variants[0])
    return await content_service.respond(db, copy)


@router.post("/posts/{post_id}/schedule", response_model=PostResponse)
async def schedule_post(
    post_id: uuid.UUID,
    payload: ScheduleRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PostResponse:
    """Schedules a post. The Beat sweep claims it when its slot arrives.

    No job is enqueued here on purpose: rescheduling this post later is then a
    plain UPDATE, with no earlier job left behind to fire a second time.
    """
    post = await content_service.get_post(db, ctx.workspace_id, post_id)
    post = await content_service.schedule_post(db, ctx, post, payload)
    return await content_service.respond(db, post)


@router.post("/posts/{post_id}/cancel", response_model=PostResponse)
async def cancel_post(
    post_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> PostResponse:
    post = await content_service.get_post(db, ctx.workspace_id, post_id)
    post = await content_service.cancel_schedule(db, ctx, post)
    return await content_service.respond(db, post)


@router.post("/posts/{post_id}/publish", response_model=PostResponse)
async def publish_post(
    post_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> PostResponse:
    """Publish Now. Validates here; the worker claims the row and executes."""
    post = await content_service.get_post(db, ctx.workspace_id, post_id)
    post = await content_service.mark_for_immediate_publish(db, ctx, post)

    # Render before committing: the commit ends this handler's unit of work, and
    # anything still unfetched on the row would need a second round trip after.
    response = await content_service.respond(db, post)

    # Commit before enqueueing: a worker that starts first would find the row
    # unchanged and decline to publish.
    await db.commit()
    celery_app.send_task("content.publish_post", args=[str(post.id)], queue="content.publish")
    return response


@router.post("/posts/{post_id}/retry", response_model=PostResponse)
async def retry_post(
    post_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> PostResponse:
    post = await content_service.get_post(db, ctx.workspace_id, post_id)
    post = await content_service.retry_post(db, ctx, post)
    response = await content_service.respond(db, post)

    await db.commit()
    celery_app.send_task("content.publish_post", args=[str(post.id)], queue="content.publish")
    return response


# ── approval workflow ────────────────────────────────────────────────────────


@router.post("/posts/{post_id}/submit", response_model=PostResponse)
async def submit_for_approval(
    post_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> PostResponse:
    post = await content_service.get_post(db, ctx.workspace_id, post_id)
    post = await content_service.submit_for_approval(db, ctx, post)
    return await content_service.respond(db, post)


@router.post("/posts/{post_id}/approve", response_model=PostResponse)
async def approve_post(
    post_id: uuid.UUID,
    payload: ReviewRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PostResponse:
    post = await content_service.get_post(db, ctx.workspace_id, post_id)
    post = await content_service.approve_post(db, ctx, post, payload.note)
    return await content_service.respond(db, post)


@router.post("/posts/{post_id}/request-changes", response_model=PostResponse)
async def request_changes(
    post_id: uuid.UUID,
    payload: ReviewRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PostResponse:
    post = await content_service.get_post(db, ctx.workspace_id, post_id)
    post = await content_service.reject_post(db, ctx, post, payload.note)
    return await content_service.respond(db, post)


@router.get("/settings/approval", response_model=ApprovalSettingsResponse)
async def get_approval_settings(ctx: Workspace_) -> ApprovalSettingsResponse:
    return ApprovalSettingsResponse(
        approval_required=content_service.approval_required(ctx.workspace),
        can_approve=content_service.can_publish(ctx),
    )


@router.put("/settings/approval", response_model=ApprovalSettingsResponse)
async def set_approval_settings(
    payload: ApprovalSettingsRequest, ctx: Workspace_
) -> ApprovalSettingsResponse:
    ctx.require_role(WorkspaceRole.ADMIN)
    # Reassign rather than mutate: SQLAlchemy only notices a JSONB change when
    # the attribute itself is set.
    ctx.workspace.settings = {
        **(ctx.workspace.settings or {}),
        content_service.APPROVAL_SETTING_KEY: payload.approval_required,
    }
    return ApprovalSettingsResponse(
        approval_required=payload.approval_required, can_approve=content_service.can_publish(ctx)
    )


# ── calendar ─────────────────────────────────────────────────────────────────


@router.get("/calendar", response_model=CalendarResponse)
async def get_calendar(
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
    start: date | None = None,
    end: date | None = None,
    timezone: str = "UTC",
) -> CalendarResponse:
    today = date.today()
    start = start or today.replace(day=1)
    end = end or start + timedelta(days=41)
    if end < start:
        raise ValidationFailedError("the calendar range ends before it starts")
    if (end - start).days > 120:
        raise ValidationFailedError("the calendar range is too wide; request 120 days or fewer")
    return await content_service.calendar(
        db, ctx.workspace_id, start=start, end=end, tz_name=timezone
    )


# ── media ────────────────────────────────────────────────────────────────────


@router.get("/media/limits", response_model=MediaLimitsResponse)
async def media_limits(ctx: Workspace_) -> MediaLimitsResponse:
    """What the composer may accept, so the client has no hardcoded copy."""
    _ = ctx
    return MediaLimitsResponse(limits=media_service.limits())


@router.post("/media", response_model=MediaAssetResponse, status_code=status.HTTP_201_CREATED)
async def upload_media(
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
    file: Annotated[UploadFile, File()],
) -> MediaAssetResponse:
    ctx.require_role(WorkspaceRole.MEMBER)
    stored = await media_service.upload(db, ctx, file)
    asset = stored.asset
    return MediaAssetResponse(
        id=asset.id,
        kind=asset.kind,
        filename=asset.filename,
        content_type=asset.content_type,
        size_bytes=asset.size_bytes,
        width=asset.width,
        height=asset.height,
        url=stored.url,
        created_at=asset.created_at,
    )


@router.delete("/media/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_media(
    asset_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> None:
    ctx.require_role(WorkspaceRole.MEMBER)
    await media_service.delete(db, ctx, asset_id)


# ── templates ────────────────────────────────────────────────────────────────


@router.get("/templates", response_model=list[TemplateResponse])
async def list_templates(
    ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[TemplateResponse]:
    templates = await content_service.list_templates(db, ctx.workspace_id)
    return [await content_service.template_response(db, t) for t in templates]


@router.post("/templates", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: TemplateCreateRequest, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> TemplateResponse:
    ctx.require_role(WorkspaceRole.MEMBER)
    template = await content_service.create_template(db, ctx, payload)
    return await content_service.template_response(db, template)


@router.patch("/templates/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: uuid.UUID,
    payload: TemplateUpdateRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TemplateResponse:
    ctx.require_role(WorkspaceRole.MEMBER)
    template = await content_service.get_template(db, ctx.workspace_id, template_id)
    template = await content_service.update_template(db, ctx, template, payload)
    return await content_service.template_response(db, template)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> None:
    ctx.require_role(WorkspaceRole.MEMBER)
    template = await content_service.get_template(db, ctx.workspace_id, template_id)
    await db.delete(template)


# ── publishing queue ─────────────────────────────────────────────────────────


async def _queue_response(db: AsyncSession, ctx: Workspace_) -> QueueResponse:  # type: ignore[valid-type]
    queue = await content_service.get_queue(db, ctx)
    items = await content_service.queued_posts(db, ctx.workspace_id)
    presentation = await content_service.build_presentation(db, items)
    return QueueResponse(
        paused=queue.paused,
        timezone=queue.timezone,
        slots=[QueueSlot(**slot) for slot in (queue.slots or [])],
        items=[content_service.to_response(post, presentation) for post in items],
        next_slot_at=content_service.next_slot_at(queue),
    )


@router.get("/queue", response_model=QueueResponse)
async def get_queue(ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]) -> QueueResponse:
    return await _queue_response(db, ctx)


@router.patch("/queue", response_model=QueueResponse)
async def update_queue(
    payload: QueueUpdateRequest, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> QueueResponse:
    await content_service.update_queue(
        db, ctx, paused=payload.paused, tz_name=payload.timezone, slots=payload.slots
    )
    return await _queue_response(db, ctx)


@router.post("/posts/{post_id}/queue", response_model=QueueResponse)
async def add_to_queue(
    post_id: uuid.UUID,
    payload: QueueAddRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QueueResponse:
    post = await content_service.get_post(db, ctx.workspace_id, post_id)
    if payload.linkedin_account_id is not None:
        account = await content_service.resolve_account(
            db, ctx.workspace_id, payload.linkedin_account_id
        )
        post.linkedin_account_id = account.id
    await content_service.add_to_queue(db, ctx, post)
    return await _queue_response(db, ctx)


@router.post("/posts/{post_id}/queue/move", response_model=QueueResponse)
async def move_in_queue(
    post_id: uuid.UUID,
    payload: QueueMoveRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QueueResponse:
    post = await content_service.get_post(db, ctx.workspace_id, post_id)
    await content_service.move_in_queue(db, ctx, post, payload.direction)
    return await _queue_response(db, ctx)


@router.delete("/posts/{post_id}/queue", response_model=QueueResponse)
async def remove_from_queue(
    post_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> QueueResponse:
    post = await content_service.get_post(db, ctx.workspace_id, post_id)
    await content_service.remove_from_queue(db, ctx, post)
    return await _queue_response(db, ctx)


# ── AI assistance ────────────────────────────────────────────────────────────
#
# Both routes return text and nothing else. There is no path from here to a
# publish: the user takes the suggestion into the editor and decides.


@router.post("/ai/improve", response_model=AiResponse)
async def ai_improve(
    payload: AiImproveRequest, ctx: Workspace_
) -> AiResponse:
    ctx.require_role(WorkspaceRole.MEMBER)
    if payload.action not in ai_content.ACTIONS:
        raise NotFoundError(f"“{payload.action}” is not an available AI action")

    variants, note = await anyio.to_thread.run_sync(
        ai_content.improve, payload.content, payload.action
    )
    return AiResponse(variants=variants, note=note)


@router.post("/ai/generate", response_model=AiResponse)
async def ai_generate(payload: AiGenerateRequest, ctx: Workspace_) -> AiResponse:
    ctx.require_role(WorkspaceRole.MEMBER)
    variants, note = await anyio.to_thread.run_sync(
        lambda: ai_content.generate(
            topic=payload.topic,
            audience=payload.audience,
            tone=payload.tone,
            goal=payload.goal,
        )
    )
    return AiResponse(variants=variants, note=note)
