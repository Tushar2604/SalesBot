"""Content Studio: post lifecycle, templates, calendar, and the publishing queue.

Like `linkedin_service`, this module never talks to LinkedIn. It validates,
persists, and lets the worker own every outbound call.

Two design decisions worth stating, because a lot follows from them:

**Scheduling is state, not a queued job.** A scheduled post is a row with
`status = SCHEDULED` and a UTC `scheduled_at`; a Beat sweep claims what is due.
Nothing here enqueues a delayed task pinned to a timestamp, so rescheduling,
cancelling and editing are ordinary UPDATEs — there is no orphaned job to hunt
down, and no way for an old job and a new one to both fire.

**Publishing is claimed, not commanded.** The API asks for a publish; the worker
decides it may proceed by transitioning the row under a lock. That is what makes
a redelivered broker message harmless.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.deps import WorkspaceContext
from app.linkedin import publishing
from app.models.content import (
    LinkedInPost,
    LinkedInPostMedia,
    MediaAsset,
    PostQueue,
    PostStatus,
    PostTemplate,
)
from app.models.linkedin import LinkedInAccount
from app.models.tenancy import NotificationType, User, Workspace, WorkspaceRole
from app.schemas.content import (
    CalendarEntry,
    CalendarResponse,
    MediaAssetResponse,
    PostAccountSummary,
    PostAnalyticsResponse,
    PostCreateRequest,
    PostMediaInput,
    PostMediaResponse,
    PostResponse,
    PostUpdateRequest,
    PublishingCapabilityResponse,
    QueueSlot,
    ScheduleRequest,
    TemplateCreateRequest,
    TemplateResponse,
    TemplateUpdateRequest,
)
from app.services import audit, media_service, notification_service

APPROVAL_SETTING_KEY = "content_approval_required"

# States a post may be moved *into* scheduling from.
_SCHEDULABLE = {
    PostStatus.DRAFT,
    PostStatus.APPROVED,
    PostStatus.SCHEDULED,
    PostStatus.FAILED,
    PostStatus.CANCELLED,
}

_HASHTAG_RE = re.compile(r"#([\wÀ-ɏЀ-ӿ][\wÀ-ɏЀ-ӿ-]*)")


# ── text statistics ──────────────────────────────────────────────────────────


def character_count(content: str) -> int:
    return len(content)


def word_count(content: str) -> int:
    return len([w for w in content.split() if w.strip()])


def hashtags(content: str) -> list[str]:
    """Hashtags in order of first appearance, without duplicates."""
    seen: list[str] = []
    for match in _HASHTAG_RE.finditer(content):
        tag = match.group(1)
        if tag not in seen:
            seen.append(tag)
    return seen


def excerpt(content: str, limit: int = 120) -> str:
    flat = " ".join(content.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


# ── permissions ──────────────────────────────────────────────────────────────


def approval_required(workspace: Workspace) -> bool:
    """Per-workspace toggle. Off by default — a solo user is not a committee."""
    return bool((workspace.settings or {}).get(APPROVAL_SETTING_KEY, False))


def can_publish(ctx: WorkspaceContext) -> bool:
    """Publishing and scheduling are admin-and-above actions.

    This product's roles are owner/admin/member. The Content Studio maps the
    brief's EDITOR onto `member` (compose and edit drafts, submit for approval)
    and ADMIN/OWNER onto publishing rights, rather than introducing a fourth
    role that every other feature would then have to understand.
    """
    return ctx.role.can_act_as(WorkspaceRole.ADMIN)


def require_publish(ctx: WorkspaceContext) -> None:
    if not can_publish(ctx):
        raise PermissionDeniedError(
            "publishing and scheduling require the admin role; you can save a "
            "draft and submit it for approval"
        )


def _require_author_or_admin(ctx: WorkspaceContext, post: LinkedInPost) -> None:
    """A member may only change their own drafts."""
    if can_publish(ctx) or post.created_by_id == ctx.user.id:
        return
    raise PermissionDeniedError("you can only edit posts you created")


def _require_editable(post: LinkedInPost) -> None:
    if not post.status.is_editable:
        raise ConflictError(
            f"a post that is {post.status.value.replace('_', ' ')} can no longer be edited"
        )


# ── timezone helpers ─────────────────────────────────────────────────────────


def zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def to_utc(day: date, clock: str, tz_name: str) -> datetime:
    """Local wall-clock -> UTC instant. The stored value is always UTC."""
    hour, minute = (int(part) for part in clock.split(":"))
    local = datetime.combine(day, time(hour, minute), tzinfo=zone(tz_name))
    return local.astimezone(UTC)


# ── presentation ─────────────────────────────────────────────────────────────


@dataclass(slots=True)
class Presentation:
    """Everything needed to render a batch of posts, fetched once."""

    accounts: dict[uuid.UUID, LinkedInAccount]
    authors: dict[uuid.UUID, str]
    media_urls: dict[uuid.UUID, str]


async def build_presentation(db: AsyncSession, posts: list[LinkedInPost]) -> Presentation:
    """Batch-loads accounts, author names and presigned media URLs.

    Done in one place so rendering a page of 50 posts is three queries plus N
    signature computations, rather than a lazy load per attribute.
    """
    account_ids = {post.linkedin_account_id for post in posts}
    author_ids = {post.created_by_id for post in posts if post.created_by_id}

    accounts: dict[uuid.UUID, LinkedInAccount] = {}
    if account_ids:
        rows = (
            (await db.execute(select(LinkedInAccount).where(LinkedInAccount.id.in_(account_ids))))
            .scalars()
            .all()
        )
        accounts = {row.id: row for row in rows}

    authors: dict[uuid.UUID, str] = {}
    if author_ids:
        rows_u = (
            (await db.execute(select(User).where(User.id.in_(author_ids)))).scalars().all()
        )
        authors = {row.id: row.full_name or row.email for row in rows_u}

    media_urls: dict[uuid.UUID, str] = {}
    for post in posts:
        for link in post.media:
            asset = link.asset
            if asset is not None and asset.id not in media_urls:
                media_urls[asset.id] = await media_service.presign(asset)

    return Presentation(accounts=accounts, authors=authors, media_urls=media_urls)


def _capability_response(account: LinkedInAccount | None) -> PublishingCapabilityResponse:
    if account is None:
        return PublishingCapabilityResponse(
            code="not_authorized",
            available=False,
            message="The LinkedIn account for this post no longer exists.",
            remedy="",
        )
    return PublishingCapabilityResponse(**publishing.capability_for(account).as_dict())


def _account_summary(account: LinkedInAccount | None) -> PostAccountSummary:
    capability = _capability_response(account)
    if account is None:
        return PostAccountSummary(
            id=uuid.UUID(int=0),
            label="Deleted account",
            full_name="",
            headline="",
            avatar_url="",
            profile_url="",
            can_publish=False,
            capability=capability,
        )
    return PostAccountSummary(
        id=account.id,
        label=account.label or account.full_name or account.login_email,
        full_name=account.full_name,
        headline=account.headline,
        avatar_url=account.avatar_url,
        profile_url=(
            f"https://www.linkedin.com/in/{account.public_id}" if account.public_id else ""
        ),
        can_publish=capability.available,
        capability=capability,
    )


def _analytics_response(
    post: LinkedInPost, account: LinkedInAccount | None
) -> PostAnalyticsResponse:
    """Real numbers when we have them; an honest "no" when we do not.

    Nothing synthesises a value here. If no upstream read has ever populated
    `post.analytics`, the response says analytics are unavailable and why.
    """
    if post.status is not PostStatus.PUBLISHED:
        return PostAnalyticsResponse(
            available=False, message="Analytics appear once the post is published."
        )

    stored = post.analytics or {}
    if stored:
        impressions = stored.get("impressions")
        engagements = sum(
            int(stored.get(key) or 0) for key in ("likes", "comments", "reposts", "clicks")
        )
        rate = (
            round(engagements / impressions, 4)
            if isinstance(impressions, int) and impressions > 0
            else None
        )
        return PostAnalyticsResponse(
            available=True,
            message="",
            impressions=stored.get("impressions"),
            likes=stored.get("likes"),
            comments=stored.get("comments"),
            reposts=stored.get("reposts"),
            clicks=stored.get("clicks"),
            engagement_rate=rate,
            updated_at=post.analytics_updated_at,
        )

    verdict = (
        publishing.analytics_capability(account)
        if account is not None
        else publishing.PublishingCapability(
            publishing.CapabilityCode.NOT_AUTHORIZED, "The LinkedIn account no longer exists."
        )
    )
    return PostAnalyticsResponse(
        available=False,
        message=verdict.message
        if not verdict.available
        else "Analytics have not been retrieved for this post yet.",
    )


def _media_response(link: LinkedInPostMedia, urls: dict[uuid.UUID, str]) -> PostMediaResponse:
    asset = link.asset
    return PostMediaResponse(
        id=link.id,
        position=link.position,
        alt_text=link.alt_text,
        asset=MediaAssetResponse(
            id=asset.id,
            kind=asset.kind,
            filename=asset.filename,
            content_type=asset.content_type,
            size_bytes=asset.size_bytes,
            width=asset.width,
            height=asset.height,
            url=urls.get(asset.id, ""),
            created_at=asset.created_at,
        ),
    )


def to_response(post: LinkedInPost, presentation: Presentation) -> PostResponse:
    account = presentation.accounts.get(post.linkedin_account_id)
    return PostResponse(
        id=post.id,
        workspace_id=post.workspace_id,
        created_by_id=post.created_by_id,
        created_by_name=presentation.authors.get(post.created_by_id, "")
        if post.created_by_id
        else "",
        account=_account_summary(account),
        content=post.content,
        visibility=post.visibility,
        status=post.status,
        is_editable=post.status.is_editable,
        character_count=character_count(post.content),
        word_count=word_count(post.content),
        hashtags=hashtags(post.content),
        scheduled_at=post.scheduled_at,
        scheduled_timezone=post.scheduled_timezone,
        queue_position=post.queue_position,
        published_at=post.published_at,
        linkedin_post_id=post.linkedin_post_id,
        linkedin_url=post.linkedin_url,
        failure_reason=post.failure_reason,
        error_code=post.error_code,
        request_id=post.request_id,
        failed_at=post.failed_at,
        attempts=post.attempts,
        submitted_for_approval_at=post.submitted_for_approval_at,
        approved_at=post.approved_at,
        approved_by_id=post.approved_by_id,
        review_note=post.review_note,
        media=[_media_response(link, presentation.media_urls) for link in post.media],
        analytics=_analytics_response(post, account),
        created_at=post.created_at,
        updated_at=post.updated_at,
    )


async def respond(db: AsyncSession, post: LinkedInPost) -> PostResponse:
    """Single-post convenience wrapper."""
    return to_response(post, await build_presentation(db, [post]))


# ── queries ──────────────────────────────────────────────────────────────────


def _base_query(workspace_id: uuid.UUID) -> Select[Any]:
    return select(LinkedInPost).where(LinkedInPost.workspace_id == workspace_id)


async def get_post(
    db: AsyncSession, workspace_id: uuid.UUID, post_id: uuid.UUID
) -> LinkedInPost:
    post = (
        await db.execute(
            _base_query(workspace_id).where(LinkedInPost.id == post_id)
        )
    ).scalar_one_or_none()
    if post is None:
        raise NotFoundError("post not found")
    return post


async def status_counts(db: AsyncSession, workspace_id: uuid.UUID) -> dict[str, int]:
    rows = (
        await db.execute(
            select(LinkedInPost.status, func.count())
            .where(LinkedInPost.workspace_id == workspace_id)
            .group_by(LinkedInPost.status)
        )
    ).all()
    counts = {status.value: 0 for status in PostStatus}
    total = 0
    for status, count in rows:
        counts[status.value] = count
        total += count
    counts["all"] = total
    return counts


async def list_posts(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    statuses: list[PostStatus] | None = None,
    account_id: uuid.UUID | None = None,
    author_id: uuid.UUID | None = None,
    search: str = "",
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[LinkedInPost], int]:
    conditions = []
    if statuses:
        conditions.append(LinkedInPost.status.in_(statuses))
    if account_id is not None:
        conditions.append(LinkedInPost.linkedin_account_id == account_id)
    if author_id is not None:
        conditions.append(LinkedInPost.created_by_id == author_id)
    if search.strip():
        conditions.append(LinkedInPost.content.ilike(f"%{search.strip()}%"))
    if date_from is not None:
        start = datetime.combine(date_from, time.min, tzinfo=UTC)
        conditions.append(
            or_(
                LinkedInPost.scheduled_at >= start,
                LinkedInPost.published_at >= start,
                LinkedInPost.created_at >= start,
            )
        )
    if date_to is not None:
        end = datetime.combine(date_to, time.max, tzinfo=UTC)
        conditions.append(
            or_(
                LinkedInPost.scheduled_at <= end,
                LinkedInPost.published_at <= end,
                LinkedInPost.created_at <= end,
            )
        )

    total = (
        await db.scalar(
            select(func.count())
            .select_from(LinkedInPost)
            .where(LinkedInPost.workspace_id == workspace_id, *conditions)
        )
    ) or 0

    stmt = (
        _base_query(workspace_id)
        .where(*conditions)
        # Newest activity first: a post's own timeline is published > scheduled >
        # created, and that is the order a studio user expects to see.
        .order_by(
            func.coalesce(
                LinkedInPost.published_at, LinkedInPost.scheduled_at, LinkedInPost.created_at
            ).desc()
        )
        .limit(limit)
        .offset(offset)
    )
    posts = list((await db.execute(stmt)).scalars().all())
    return posts, total


# ── account resolution ───────────────────────────────────────────────────────


async def resolve_account(
    db: AsyncSession, workspace_id: uuid.UUID, account_id: uuid.UUID
) -> LinkedInAccount:
    """The workspace-ownership check for "posting as".

    A post may only ever be bound to a LinkedIn account belonging to the same
    workspace; this is the single place that is established.
    """
    account = (
        await db.execute(
            select(LinkedInAccount).where(
                LinkedInAccount.id == account_id,
                LinkedInAccount.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise NotFoundError("LinkedIn account not found in this workspace")
    return account


# ── media attachment ─────────────────────────────────────────────────────────


async def _apply_media(
    db: AsyncSession, ctx: WorkspaceContext, post: LinkedInPost, media: list[PostMediaInput]
) -> None:
    """Replaces the post's attachments with exactly this ordered set."""
    assets = await media_service.get_assets(
        db, ctx.workspace_id, [item.media_asset_id for item in media]
    )
    media_service.validate_attachment_set(assets)

    # Clear first and flush, so the (post_id, position) unique constraint cannot
    # collide with rows that are about to be deleted anyway.
    post.media.clear()
    await db.flush()

    for index, (item, asset) in enumerate(zip(media, assets, strict=True)):
        post.media.append(
            LinkedInPostMedia(
                media_asset_id=asset.id,
                position=index,
                alt_text=item.alt_text,
                asset=asset,
            )
        )
    await db.flush()


# ── create / update / delete ─────────────────────────────────────────────────


async def create_post(
    db: AsyncSession, ctx: WorkspaceContext, payload: PostCreateRequest
) -> LinkedInPost:
    account = await resolve_account(db, ctx.workspace_id, payload.linkedin_account_id)

    post = LinkedInPost(
        workspace_id=ctx.workspace_id,
        created_by_id=ctx.user.id,
        linkedin_account_id=account.id,
        content=payload.content,
        visibility=payload.visibility,
        status=PostStatus.DRAFT,
        # Stated explicitly so presenting this fresh object never emits a lazy
        # SELECT — that would be IO from sync code inside an async handler.
        media=[],
    )
    db.add(post)
    await db.flush()

    if payload.media:
        await _apply_media(db, ctx, post, payload.media)

    await audit.record(
        db,
        "content_post.created",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="linkedin_post",
        target_id=post.id,
        metadata={"account_id": str(account.id)},
    )
    return post


async def update_post(
    db: AsyncSession, ctx: WorkspaceContext, post: LinkedInPost, payload: PostUpdateRequest
) -> LinkedInPost:
    """Also the autosave path, so it must stay cheap and side-effect free."""
    _require_author_or_admin(ctx, post)
    _require_editable(post)

    if payload.linkedin_account_id is not None:
        account = await resolve_account(db, ctx.workspace_id, payload.linkedin_account_id)
        post.linkedin_account_id = account.id
    if payload.content is not None:
        post.content = payload.content
    if payload.visibility is not None:
        post.visibility = payload.visibility
    if payload.media is not None:
        await _apply_media(db, ctx, post, payload.media)

    # Editing a scheduled post keeps its slot but clears any stale failure text,
    # so the card does not show an error that no longer applies.
    if post.status is PostStatus.FAILED:
        post.failure_reason = ""
        post.error_code = ""
        post.request_id = ""
    return post


async def delete_post(db: AsyncSession, ctx: WorkspaceContext, post: LinkedInPost) -> None:
    _require_author_or_admin(ctx, post)
    if post.status is PostStatus.PUBLISHING:
        raise ConflictError(
            "this post is being published right now; wait for it to finish before deleting it"
        )

    await audit.record(
        db,
        "content_post.deleted",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="linkedin_post",
        target_id=post.id,
        metadata={"status": post.status.value},
    )
    await db.delete(post)


async def duplicate_post(
    db: AsyncSession, ctx: WorkspaceContext, post: LinkedInPost, *, content: str | None = None
) -> LinkedInPost:
    """Always produces a DRAFT — a copy is never a scheduled or published thing."""
    copy = LinkedInPost(
        workspace_id=ctx.workspace_id,
        created_by_id=ctx.user.id,
        linkedin_account_id=post.linkedin_account_id,
        content=post.content if content is None else content,
        visibility=post.visibility,
        status=PostStatus.DRAFT,
        media=[],
    )
    db.add(copy)
    await db.flush()

    for link in post.media:
        copy.media.append(
            LinkedInPostMedia(
                media_asset_id=link.media_asset_id,
                position=link.position,
                alt_text=link.alt_text,
                asset=link.asset,
            )
        )
    await db.flush()

    await audit.record(
        db,
        "content_post.duplicated",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="linkedin_post",
        target_id=copy.id,
        metadata={"source_post_id": str(post.id)},
    )
    return copy


# ── approval workflow ────────────────────────────────────────────────────────


async def submit_for_approval(
    db: AsyncSession, ctx: WorkspaceContext, post: LinkedInPost
) -> LinkedInPost:
    _require_author_or_admin(ctx, post)
    if post.status not in (PostStatus.DRAFT, PostStatus.FAILED, PostStatus.CANCELLED):
        raise ConflictError("only a draft can be submitted for approval")

    post.status = PostStatus.PENDING_APPROVAL
    post.submitted_for_approval_at = datetime.now(UTC)
    post.review_note = ""

    await notification_service.create(
        db,
        ctx.workspace_id,
        NotificationType.POST_NEEDS_APPROVAL,
        f"{ctx.user.full_name or ctx.user.email} submitted a LinkedIn post for approval",
        body=excerpt(post.content),
        link=f"/content/{post.id}",
    )
    await audit.record(
        db,
        "content_post.submitted_for_approval",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="linkedin_post",
        target_id=post.id,
    )
    return post


async def approve_post(
    db: AsyncSession, ctx: WorkspaceContext, post: LinkedInPost, note: str
) -> LinkedInPost:
    require_publish(ctx)
    if post.status is not PostStatus.PENDING_APPROVAL:
        raise ConflictError("this post is not awaiting approval")

    post.status = PostStatus.APPROVED
    post.approved_by_id = ctx.user.id
    post.approved_at = datetime.now(UTC)
    post.review_note = note

    await notification_service.create(
        db,
        ctx.workspace_id,
        NotificationType.POST_APPROVED,
        "A LinkedIn post was approved",
        body=excerpt(post.content),
        link=f"/content/{post.id}",
    )
    await audit.record(
        db,
        "content_post.approved",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="linkedin_post",
        target_id=post.id,
    )
    return post


async def reject_post(
    db: AsyncSession, ctx: WorkspaceContext, post: LinkedInPost, note: str
) -> LinkedInPost:
    require_publish(ctx)
    if post.status is not PostStatus.PENDING_APPROVAL:
        raise ConflictError("this post is not awaiting approval")

    post.status = PostStatus.DRAFT
    post.review_note = note
    post.submitted_for_approval_at = None

    await audit.record(
        db,
        "content_post.changes_requested",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="linkedin_post",
        target_id=post.id,
        note=note,
    )
    return post


def _guard_approval(ctx: WorkspaceContext, post: LinkedInPost) -> None:
    """Blocks scheduling/publishing when the workspace requires sign-off."""
    if not approval_required(ctx.workspace):
        return
    if post.status is PostStatus.APPROVED:
        return
    # An admin scheduling their own post still needs the workflow to have run,
    # otherwise the setting means nothing.
    raise ConflictError(
        "this workspace requires posts to be approved before they can be scheduled "
        "or published"
    )


# ── scheduling ───────────────────────────────────────────────────────────────


def _guard_publishable(post: LinkedInPost, account: LinkedInAccount) -> None:
    """Refuses to schedule content LinkedIn would certainly reject."""
    if not post.content.strip() and not post.media:
        raise ValidationFailedError("a post needs text or media before it can go out")
    if len(post.content) > publishing.MAX_COMMENTARY_CHARS:
        raise ValidationFailedError(
            f"LinkedIn limits a post to {publishing.MAX_COMMENTARY_CHARS} characters; "
            f"this one is {len(post.content)}"
        )

    capability = publishing.capability_for(account)
    if not capability.available:
        # Not a validation error: nothing about the *post* is wrong. The account
        # needs authorizing, and the UI has a dedicated state for that.
        raise ConflictError(capability.message, details=capability.as_dict())


async def schedule_post(
    db: AsyncSession, ctx: WorkspaceContext, post: LinkedInPost, payload: ScheduleRequest
) -> LinkedInPost:
    require_publish(ctx)
    _guard_approval(ctx, post)

    if post.status not in _SCHEDULABLE:
        raise ConflictError(
            f"a post that is {post.status.value.replace('_', ' ')} cannot be scheduled"
        )

    account = await resolve_account(db, ctx.workspace_id, post.linkedin_account_id)
    _guard_publishable(post, account)

    when = to_utc(payload.scheduled_date, payload.scheduled_time, payload.timezone)
    if when <= datetime.now(UTC):
        raise ValidationFailedError("that time is in the past; pick a future slot")

    post.status = PostStatus.SCHEDULED
    post.scheduled_at = when
    post.scheduled_timezone = payload.timezone
    post.queue_position = None
    post.failure_reason = ""
    post.error_code = ""
    post.request_id = ""
    post.failed_at = None

    await notification_service.create(
        db,
        ctx.workspace_id,
        NotificationType.POST_SCHEDULED,
        "LinkedIn post scheduled",
        body=f"{excerpt(post.content, 80)} — {when:%d %b %Y %H:%M} UTC",
        link=f"/content/{post.id}",
    )
    await audit.record(
        db,
        "content_post.scheduled",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="linkedin_post",
        target_id=post.id,
        metadata={"scheduled_at": when.isoformat(), "timezone": payload.timezone},
    )
    return post


async def cancel_schedule(
    db: AsyncSession, ctx: WorkspaceContext, post: LinkedInPost
) -> LinkedInPost:
    """Takes a post out of the schedule. There is no job to cancel — the sweep
    reads status, so clearing it here is the cancellation."""
    require_publish(ctx)
    if post.status not in (PostStatus.SCHEDULED, PostStatus.PENDING_APPROVAL, PostStatus.APPROVED):
        raise ConflictError(
            f"a post that is {post.status.value.replace('_', ' ')} cannot be cancelled"
        )

    post.status = PostStatus.CANCELLED
    post.scheduled_at = None
    post.queue_position = None

    await audit.record(
        db,
        "content_post.cancelled",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="linkedin_post",
        target_id=post.id,
    )
    return post


async def mark_for_immediate_publish(
    db: AsyncSession, ctx: WorkspaceContext, post: LinkedInPost
) -> LinkedInPost:
    """Publish Now: validate here, let the worker claim and execute.

    The status does not jump straight to PUBLISHING: that transition belongs to
    the worker, under a row lock, and is exactly what prevents two publishes.
    """
    require_publish(ctx)
    _guard_approval(ctx, post)

    if post.status is PostStatus.PUBLISHED:
        raise ConflictError("this post has already been published")
    if post.status is PostStatus.PUBLISHING:
        raise ConflictError("this post is already being published")

    account = await resolve_account(db, ctx.workspace_id, post.linkedin_account_id)
    _guard_publishable(post, account)

    post.status = PostStatus.SCHEDULED
    post.scheduled_at = datetime.now(UTC)
    post.scheduled_timezone = post.scheduled_timezone or ctx.user.timezone or "UTC"
    post.queue_position = None
    post.failure_reason = ""
    post.error_code = ""
    post.request_id = ""
    post.failed_at = None

    await audit.record(
        db,
        "content_post.publish_requested",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="linkedin_post",
        target_id=post.id,
    )
    return post


async def retry_post(db: AsyncSession, ctx: WorkspaceContext, post: LinkedInPost) -> LinkedInPost:
    """Explicit, user-initiated retry of a failed publish."""
    require_publish(ctx)
    if post.status is not PostStatus.FAILED:
        raise ConflictError("only a failed post can be retried")
    return await mark_for_immediate_publish(db, ctx, post)


# ── calendar ─────────────────────────────────────────────────────────────────


async def calendar(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    start: date,
    end: date,
    tz_name: str,
) -> CalendarResponse:
    """Posts with a date in the window, expressed in the viewer's timezone."""
    tz = zone(tz_name)
    window_start = datetime.combine(start, time.min, tzinfo=tz).astimezone(UTC)
    window_end = datetime.combine(end, time.max, tzinfo=tz).astimezone(UTC)

    timeline = func.coalesce(
        LinkedInPost.published_at, LinkedInPost.scheduled_at, LinkedInPost.created_at
    )
    posts = list(
        (
            await db.execute(
                _base_query(workspace_id)
                .where(timeline >= window_start, timeline <= window_end)
                .order_by(timeline.asc())
            )
        )
        .scalars()
        .all()
    )

    accounts = (await build_presentation(db, posts)).accounts
    entries: list[CalendarEntry] = []
    for post in posts:
        at = post.published_at or post.scheduled_at or post.created_at
        if at.tzinfo is None:
            at = at.replace(tzinfo=UTC)
        local = at.astimezone(tz)
        account = accounts.get(post.linkedin_account_id)
        entries.append(
            CalendarEntry(
                id=post.id,
                status=post.status,
                excerpt=excerpt(post.content, 90),
                at=at,
                local_date=local.date(),
                local_time=f"{local:%H:%M}",
                timezone=tz_name,
                account_label=(account.label or account.full_name) if account else "",
                has_media=bool(post.media),
            )
        )

    return CalendarResponse(start=start, end=end, timezone=tz_name, entries=entries)


# ── templates ────────────────────────────────────────────────────────────────


async def list_templates(db: AsyncSession, workspace_id: uuid.UUID) -> list[PostTemplate]:
    stmt = (
        select(PostTemplate)
        .where(PostTemplate.workspace_id == workspace_id)
        .order_by(PostTemplate.updated_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def get_template(
    db: AsyncSession, workspace_id: uuid.UUID, template_id: uuid.UUID
) -> PostTemplate:
    template = await db.get(PostTemplate, template_id)
    if template is None or template.workspace_id != workspace_id:
        raise NotFoundError("template not found")
    return template


async def create_template(
    db: AsyncSession, ctx: WorkspaceContext, payload: TemplateCreateRequest
) -> PostTemplate:
    if payload.media_asset_ids:
        await media_service.get_assets(db, ctx.workspace_id, payload.media_asset_ids)

    template = PostTemplate(
        workspace_id=ctx.workspace_id,
        created_by_id=ctx.user.id,
        name=payload.name.strip(),
        content=payload.content,
        media_asset_ids=[str(a) for a in payload.media_asset_ids],
    )
    db.add(template)
    await db.flush()

    await audit.record(
        db,
        "post_template.created",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="post_template",
        target_id=template.id,
    )
    return template


async def update_template(
    db: AsyncSession, ctx: WorkspaceContext, template: PostTemplate, payload: TemplateUpdateRequest
) -> PostTemplate:
    if payload.name is not None:
        template.name = payload.name.strip()
    if payload.content is not None:
        template.content = payload.content
    if payload.media_asset_ids is not None:
        await media_service.get_assets(db, ctx.workspace_id, payload.media_asset_ids)
        template.media_asset_ids = [str(a) for a in payload.media_asset_ids]
    return template


async def template_response(db: AsyncSession, template: PostTemplate) -> TemplateResponse:
    asset_ids = [uuid.UUID(value) for value in template.media_asset_ids or []]
    assets: list[MediaAsset] = []
    if asset_ids:
        rows = (
            (await db.execute(select(MediaAsset).where(MediaAsset.id.in_(asset_ids))))
            .scalars()
            .all()
        )
        by_id = {row.id: row for row in rows}
        assets = [by_id[a] for a in asset_ids if a in by_id]

    return TemplateResponse(
        id=template.id,
        name=template.name,
        content=template.content,
        media=[
            MediaAssetResponse(
                id=asset.id,
                kind=asset.kind,
                filename=asset.filename,
                content_type=asset.content_type,
                size_bytes=asset.size_bytes,
                width=asset.width,
                height=asset.height,
                url=await media_service.presign(asset),
                created_at=asset.created_at,
            )
            for asset in assets
        ],
        created_by_id=template.created_by_id,
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


# ── publishing queue ─────────────────────────────────────────────────────────

DEFAULT_SLOTS: list[dict[str, Any]] = [
    {"weekday": 0, "time": "09:00"},
    {"weekday": 2, "time": "11:00"},
    {"weekday": 4, "time": "17:00"},
]


async def get_queue(db: AsyncSession, ctx: WorkspaceContext) -> PostQueue:
    """Get-or-create the workspace's single queue configuration."""
    queue = (
        await db.execute(select(PostQueue).where(PostQueue.workspace_id == ctx.workspace_id))
    ).scalar_one_or_none()
    if queue is None:
        queue = PostQueue(
            workspace_id=ctx.workspace_id,
            timezone=ctx.user.timezone or "UTC",
            slots=list(DEFAULT_SLOTS),
        )
        db.add(queue)
        await db.flush()
    return queue


def _slot_times(queue: PostQueue, *, after: datetime, count: int) -> list[datetime]:
    """The next `count` slot instants strictly after `after`, in UTC."""
    slots = sorted(
        (QueueSlot(**slot) for slot in (queue.slots or [])),
        key=lambda s: (s.weekday, s.time),
    )
    if not slots:
        return []

    tz = zone(queue.timezone)
    cursor = after.astimezone(tz)
    found: list[datetime] = []
    # Four weeks of look-ahead is plenty for any queue a human maintains, and
    # bounds the loop no matter how the slots are configured.
    for day_offset in range(0, 28):
        day = (cursor + timedelta(days=day_offset)).date()
        for slot in slots:
            if day.weekday() != slot.weekday:
                continue
            hour, minute = (int(p) for p in slot.time.split(":"))
            moment = datetime.combine(day, time(hour, minute), tzinfo=tz).astimezone(UTC)
            if moment > after:
                found.append(moment)
                if len(found) >= count:
                    return found
    return found


async def queued_posts(db: AsyncSession, workspace_id: uuid.UUID) -> list[LinkedInPost]:
    stmt = (
        _base_query(workspace_id)
        .where(LinkedInPost.queue_position.isnot(None), LinkedInPost.status == PostStatus.SCHEDULED)
        .order_by(LinkedInPost.queue_position.asc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def _restack_queue(db: AsyncSession, ctx: WorkspaceContext, queue: PostQueue) -> None:
    """Re-assigns slot times to every queued post, in queue order.

    Called after any ordering change so positions and times never disagree.
    """
    items = await queued_posts(db, ctx.workspace_id)
    times = _slot_times(queue, after=datetime.now(UTC), count=len(items))
    for index, post in enumerate(items):
        post.queue_position = index
        if index < len(times):
            post.scheduled_at = times[index]
            post.scheduled_timezone = queue.timezone


async def add_to_queue(
    db: AsyncSession, ctx: WorkspaceContext, post: LinkedInPost
) -> LinkedInPost:
    require_publish(ctx)
    _guard_approval(ctx, post)

    if post.status not in _SCHEDULABLE:
        raise ConflictError(
            f"a post that is {post.status.value.replace('_', ' ')} cannot be queued"
        )

    account = await resolve_account(db, ctx.workspace_id, post.linkedin_account_id)
    _guard_publishable(post, account)

    queue = await get_queue(db, ctx)
    if not queue.slots:
        raise ValidationFailedError(
            "the publishing queue has no time slots yet; add at least one first"
        )

    existing = await queued_posts(db, ctx.workspace_id)
    post.status = PostStatus.SCHEDULED
    post.queue_position = len(existing)
    post.failure_reason = ""
    post.error_code = ""
    post.failed_at = None
    await db.flush()

    await _restack_queue(db, ctx, queue)
    await audit.record(
        db,
        "content_post.queued",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="linkedin_post",
        target_id=post.id,
    )
    return post


async def move_in_queue(
    db: AsyncSession, ctx: WorkspaceContext, post: LinkedInPost, direction: str
) -> None:
    require_publish(ctx)
    if post.queue_position is None:
        raise ConflictError("this post is not in the queue")

    items = await queued_posts(db, ctx.workspace_id)
    index = next((i for i, item in enumerate(items) if item.id == post.id), None)
    if index is None:
        raise ConflictError("this post is not in the queue")

    target = index - 1 if direction == "up" else index + 1
    if target < 0 or target >= len(items):
        return  # already at the end; a no-op, not an error

    items[index], items[target] = items[target], items[index]
    for position, item in enumerate(items):
        item.queue_position = position
    await db.flush()

    await _restack_queue(db, ctx, await get_queue(db, ctx))


async def remove_from_queue(
    db: AsyncSession, ctx: WorkspaceContext, post: LinkedInPost
) -> LinkedInPost:
    require_publish(ctx)
    post.queue_position = None
    post.status = PostStatus.DRAFT
    post.scheduled_at = None
    await db.flush()
    await _restack_queue(db, ctx, await get_queue(db, ctx))
    return post


async def update_queue(
    db: AsyncSession, ctx: WorkspaceContext, *, paused: bool | None, tz_name: str | None,
    slots: list[QueueSlot] | None,
) -> PostQueue:
    require_publish(ctx)
    queue = await get_queue(db, ctx)

    if paused is not None:
        queue.paused = paused
    if tz_name is not None:
        queue.timezone = tz_name
    if slots is not None:
        queue.slots = [slot.model_dump() for slot in slots]

    await db.flush()
    if slots is not None or tz_name is not None:
        await _restack_queue(db, ctx, queue)

    await audit.record(
        db,
        "post_queue.updated",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="post_queue",
        target_id=queue.id,
        metadata={"paused": queue.paused, "slots": queue.slots},
    )
    return queue


def next_slot_at(queue: PostQueue) -> datetime | None:
    upcoming = _slot_times(queue, after=datetime.now(UTC), count=1)
    return upcoming[0] if upcoming else None
