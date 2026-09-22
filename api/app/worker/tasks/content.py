"""Publishing worker: the one place a post actually reaches LinkedIn.

The guarantee this module exists to provide is **a post is published at most
once**. LinkedIn's create-post endpoint is not something we can safely call
twice and reconcile afterwards, so the protection is built here:

1. A post is *claimed*, not commanded. The worker takes a row lock, checks the
   status is still `SCHEDULED`, and only then moves it to `PUBLISHING` and
   writes a `publish_key` unique to (post, attempt). A broker redelivery finds
   the row in `PUBLISHING` and does nothing.
2. The claim commits before any network call. If the worker dies mid-publish,
   the row stays `PUBLISHING` — visibly stuck rather than silently republished.
   The sweep later fails it with an explicit "status unknown" message, because
   re-sending a post that may already be live is the one outcome worse than an
   error.
3. Automatic retries are bounded and only for transient classes. Everything else
   goes straight to `FAILED` with a reason the user can act on.

Scheduling itself is not a delayed job. `content.sweep_due` runs on Beat and
claims whatever is due, so rescheduling or cancelling a post is an ordinary
UPDATE with no orphaned job left behind.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db import session_scope
from app.linkedin import publishing
from app.models.content import LinkedInPost, LinkedInPostMedia, MediaKind, PostStatus
from app.models.linkedin import LinkedInAccount
from app.models.tenancy import NotificationType
from app.services import audit, media_service, notification_service
from app.worker.celery_app import celery_app

log = get_logger(__name__)

# Automatic attempts for transient failures only. A user-initiated retry starts
# this budget again, which is the difference between "the system keeps trying
# forever" and "the person decides".
MAX_AUTO_ATTEMPTS = 3
RETRY_BACKOFF = (timedelta(minutes=2), timedelta(minutes=10), timedelta(minutes=30))

# A publish that has been in flight longer than this is treated as unresolved.
STUCK_AFTER = timedelta(minutes=15)

# How far past its slot a post may still be published. Beyond this the timing is
# no longer what the user asked for, so it is failed rather than posted late.
MAX_LATENESS = timedelta(hours=6)


def _notify_failure(db: Session, post: LinkedInPost, reason: str) -> None:
    notification_service.create_sync(
        db,
        post.workspace_id,
        NotificationType.POST_FAILED,
        "LinkedIn post failed to publish",
        body=reason[:400],
        link=f"/content/{post.id}",
    )


def _fail(db: Session, post: LinkedInPost, error: publishing.PublishingError) -> None:
    now = datetime.now(UTC)
    post.status = PostStatus.FAILED
    post.failure_reason = error.message[:2000]
    post.error_code = error.code[:80]
    post.request_id = error.request_id
    post.failed_at = now
    post.publish_key = None

    log.warning(
        "content.publish_failed",
        post_id=str(post.id),
        code=error.code,
        request_id=error.request_id,
        attempts=post.attempts,
    )
    _notify_failure(db, post, error.message)


def _requeue(post: LinkedInPost, error: publishing.PublishingError) -> None:
    """Transient failure: put the post back in the schedule with backoff."""
    index = min(post.attempts - 1, len(RETRY_BACKOFF) - 1)
    post.status = PostStatus.SCHEDULED
    post.scheduled_at = datetime.now(UTC) + RETRY_BACKOFF[max(index, 0)]
    post.failure_reason = error.message[:2000]
    post.error_code = error.code[:80]
    post.request_id = error.request_id
    post.publish_key = None

    log.info(
        "content.publish_retry_scheduled",
        post_id=str(post.id),
        attempts=post.attempts,
        next_attempt_at=post.scheduled_at.isoformat(),
    )


def _claim(db: Session, post_id: str) -> tuple[LinkedInPost, LinkedInAccount] | None:
    """Locks the row and transitions it into PUBLISHING, or declines.

    Returns None whenever this worker must not publish — already published,
    cancelled, claimed by someone else, or not actually due.
    """
    now = datetime.now(UTC)
    post = db.execute(
        select(LinkedInPost).where(LinkedInPost.id == uuid.UUID(post_id)).with_for_update()
    ).scalar_one_or_none()
    if post is None:
        log.info("content.publish_skipped", post_id=post_id, reason="post no longer exists")
        return None

    if post.status is not PostStatus.SCHEDULED:
        # The common, expected case on a redelivery.
        log.info("content.publish_skipped", post_id=post_id, reason=f"status={post.status.value}")
        return None

    if post.scheduled_at is not None:
        scheduled_at = post.scheduled_at
        if scheduled_at.tzinfo is None:
            scheduled_at = scheduled_at.replace(tzinfo=UTC)
        if scheduled_at > now + timedelta(seconds=30):
            log.info("content.publish_skipped", post_id=post_id, reason="not due yet")
            return None
        if now - scheduled_at > MAX_LATENESS:
            _fail(
                db,
                post,
                publishing.PublishingError(
                    "This post was not published within six hours of its scheduled "
                    "time, so it was not sent. Reschedule it if you still want it to "
                    "go out.",
                    code="too_late",
                ),
            )
            return None

    account = db.get(LinkedInAccount, post.linkedin_account_id)
    if account is None or account.workspace_id != post.workspace_id:
        _fail(
            db,
            post,
            publishing.PublishingError(
                "The LinkedIn account for this post is no longer available.",
                code="account_missing",
            ),
        )
        return None

    capability = publishing.capability_for(account, now=now)
    if not capability.available:
        _fail(db, post, publishing.PublishingError(capability.message, code=capability.code.value))
        if capability.code in (
            publishing.CapabilityCode.EXPIRED,
            publishing.CapabilityCode.REVOKED,
        ):
            notification_service.create_sync(
                db,
                post.workspace_id,
                NotificationType.PUBLISHING_AUTH_EXPIRED,
                f"Reconnect {account.label or account.full_name or 'your LinkedIn account'}",
                body=capability.message,
                link="/accounts",
            )
        return None

    post.status = PostStatus.PUBLISHING
    post.attempts += 1
    post.publishing_started_at = now
    # UNIQUE across the table: two claims that somehow raced past the row lock
    # would compute the same key and one of them would fail to commit.
    post.publish_key = LinkedInPost.build_publish_key(post.id, post.attempts)
    return post, account


def _upload_media(
    db: Session, publisher: publishing.LinkedInPublisher, links: list[LinkedInPostMedia]
) -> list[publishing.UploadedMedia]:
    """Registers each attachment with LinkedIn, reusing any cached URN."""
    uploaded: list[publishing.UploadedMedia] = []

    for link in sorted(links, key=lambda item: item.position):
        asset = link.asset
        if asset is None:
            raise publishing.PublishingError(
                "An attachment on this post no longer exists.", code="media_missing"
            )

        if link.linkedin_asset_urn:
            # A previous attempt already got the bytes upstream; re-uploading
            # would burn bandwidth and create an orphan asset.
            uploaded.append(
                publishing.UploadedMedia(
                    urn=link.linkedin_asset_urn,
                    kind=asset.kind,
                    alt_text=link.alt_text,
                    title=asset.filename,
                )
            )
            continue

        try:
            data = media_service.download_sync(asset)
        except Exception as exc:
            raise publishing.PublishingError(
                "An attachment could not be read from storage.",
                code="media_read_failed",
                retryable=True,
            ) from exc

        if asset.kind is MediaKind.IMAGE:
            result = publisher.upload_image(data, alt_text=link.alt_text)
        elif asset.kind is MediaKind.VIDEO:
            result = publisher.upload_video(data, title=asset.filename)
        else:
            result = publisher.upload_document(data, title=asset.filename)

        link.linkedin_asset_urn = result.urn
        db.flush()
        uploaded.append(result)

    return uploaded


@celery_app.task(name="content.publish_post", bind=True, max_retries=0)
def publish_post(self: Any, post_id: str) -> dict[str, str]:
    """Publishes one post. Safe to redeliver; will not publish twice."""
    _ = self

    # ── transaction 1: claim ────────────────────────────────────────────────
    with session_scope() as db:
        claimed = _claim(db, post_id)
        if claimed is None:
            return {"status": "skipped"}
        post, account = claimed
        try:
            db.flush()
        except IntegrityError:
            # Another claim won the publish_key race.
            db.rollback()
            log.info("content.publish_skipped", post_id=post_id, reason="claimed elsewhere")
            return {"status": "skipped"}
        workspace_id = post.workspace_id
        publish_key = post.publish_key or ""
        commentary = post.content
        visibility = post.visibility.value

    # ── transaction 2: publish and record ───────────────────────────────────
    with session_scope() as db:
        post = db.execute(
            select(LinkedInPost).where(LinkedInPost.id == uuid.UUID(post_id)).with_for_update()
        ).scalar_one()
        account = db.get(LinkedInAccount, post.linkedin_account_id)
        if account is None:
            _fail(
                db,
                post,
                publishing.PublishingError(
                    "The LinkedIn account for this post is no longer available.",
                    code="account_missing",
                ),
            )
            return {"status": "failed"}

        try:
            with publishing.build_publisher(account) as publisher:
                media = _upload_media(db, publisher, list(post.media))
                result = publisher.create_post(
                    commentary,
                    visibility=visibility,
                    media=media,
                    idempotency_key=publish_key,
                )
        except publishing.PublishingError as error:
            if error.auth_lost:
                publishing.clear_grant(account, reason=error.message)
                notification_service.create_sync(
                    db,
                    workspace_id,
                    NotificationType.PUBLISHING_AUTH_EXPIRED,
                    f"Reconnect {account.label or account.full_name or 'your LinkedIn account'}",
                    body=error.message,
                    link="/accounts",
                )
                _fail(db, post, error)
            elif error.retryable and post.attempts < MAX_AUTO_ATTEMPTS:
                _requeue(post, error)
            else:
                _fail(db, post, error)

            audit.record_sync(
                db,
                "content_post.publish_failed",
                workspace_id=workspace_id,
                target_type="linkedin_post",
                target_id=post.id,
                metadata={"code": error.code, "request_id": error.request_id},
            )
            return {"status": post.status.value, "code": error.code}
        except Exception as exc:
            _fail(
                db,
                post,
                publishing.PublishingError(
                    "Publishing failed unexpectedly. The post was not sent.",
                    code="unexpected_error",
                ),
            )
            log.error("content.publish_unexpected", post_id=post_id, error=str(exc), exc_info=True)
            return {"status": "failed", "code": "unexpected_error"}

        now = datetime.now(UTC)
        post.status = PostStatus.PUBLISHED
        post.published_at = now
        post.linkedin_post_id = result.urn[:200]
        post.linkedin_url = result.url[:400]
        post.failure_reason = ""
        post.error_code = ""
        post.request_id = ""
        post.failed_at = None
        post.queue_position = None

        notification_service.create_sync(
            db,
            workspace_id,
            NotificationType.POST_PUBLISHED,
            "LinkedIn post published",
            body=(post.content[:200] or "Your post is live on LinkedIn."),
            link=f"/content/{post.id}",
        )
        audit.record_sync(
            db,
            "content_post.published",
            workspace_id=workspace_id,
            target_type="linkedin_post",
            target_id=post.id,
            metadata={"linkedin_post_id": post.linkedin_post_id},
        )
        log.info(
            "content.published",
            post_id=str(post.id),
            linkedin_post_id=post.linkedin_post_id,
            attempts=post.attempts,
        )

    return {"status": "published"}


@celery_app.task(name="content.sweep_due")
def sweep_due() -> dict[str, int]:
    """Beat entry point: dispatch everything due, and resolve stuck publishes.

    This is the only thing that turns a scheduled post into a running publish,
    which is why cancelling one is just a status change.
    """
    now = datetime.now(UTC)
    dispatched = 0
    stuck = 0

    with session_scope() as db:
        # Posts whose slot has arrived. SKIP LOCKED so two beats never fight.
        due = (
            db.execute(
                select(LinkedInPost)
                .where(
                    LinkedInPost.status == PostStatus.SCHEDULED,
                    LinkedInPost.scheduled_at.isnot(None),
                    LinkedInPost.scheduled_at <= now,
                )
                .order_by(LinkedInPost.scheduled_at.asc())
                .limit(100)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        due_ids = [str(post.id) for post in due]

        # A publish that never reported back. Deliberately *not* retried: the
        # post may already be live on LinkedIn, and a duplicate is worse than an
        # error the user can resolve by looking at their profile.
        abandoned = (
            db.execute(
                select(LinkedInPost)
                .where(
                    LinkedInPost.status == PostStatus.PUBLISHING,
                    LinkedInPost.publishing_started_at.isnot(None),
                    LinkedInPost.publishing_started_at < now - STUCK_AFTER,
                )
                .limit(50)
                .with_for_update(skip_locked=True)
            )
            .scalars()
            .all()
        )
        for post in abandoned:
            _fail(
                db,
                post,
                publishing.PublishingError(
                    "Publishing was interrupted and its outcome is unknown. Check "
                    "your LinkedIn profile before retrying — the post may already "
                    "be live.",
                    code="interrupted",
                ),
            )
            stuck += 1

    # Send outside the transaction: a task that starts before the claim is
    # visible would find the row unchanged and skip.
    for post_id in due_ids:
        celery_app.send_task("content.publish_post", args=[post_id], queue="content.publish")
        dispatched += 1

    if dispatched or stuck:
        log.info("content.sweep", dispatched=dispatched, stuck=stuck)
    return {"dispatched": dispatched, "stuck": stuck}
