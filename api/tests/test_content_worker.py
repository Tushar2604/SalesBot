"""The publishing worker, against a real database.

This file exists for one property above all others: **a post is published at
most once.** The tests below drive the worker the way production does — with
redeliveries, races, interrupted runs and expired credentials — and assert that
the number of calls that reach LinkedIn is exactly the number of posts.

The LinkedIn publisher itself is replaced with a recorder; what it would have
sent over the wire is a separate concern from whether we let it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

import pytest
from sqlalchemy.orm import Session

from app.core.crypto import encrypt_str
from app.linkedin import publishing
from app.linkedin.publishing import POST_SCOPE, PublishedPost, PublishingError
from app.models.content import LinkedInPost, LinkedInPostMedia, MediaAsset, MediaKind, PostStatus
from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus
from app.models.tenancy import Notification, User, Workspace
from app.worker.tasks import content as worker

# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def worker_session(monkeypatch: pytest.MonkeyPatch, sdb: Session) -> Session:
    """Points the worker's `session_scope()` at the test's rolled-back session.

    `commit()` is neutralised into a flush: the worker commits between its claim
    and its publish, and a real commit here would end the outer transaction the
    fixture rolls back.
    """
    from contextlib import contextmanager

    @contextmanager
    def fake_scope():  # type: ignore[no-untyped-def]
        try:
            yield sdb
            sdb.flush()
        except Exception:
            raise

    monkeypatch.setattr(worker, "session_scope", fake_scope)
    return sdb


class RecordingPublisher:
    """Stands in for LinkedIn. Counts every post it is asked to create."""

    calls: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, *, fail_with: PublishingError | None = None) -> None:
        self._fail_with = fail_with

    def __enter__(self) -> RecordingPublisher:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def close(self) -> None:
        return None

    def upload_image(self, data: bytes, *, alt_text: str = "") -> publishing.UploadedMedia:
        RecordingPublisher.calls.append({"kind": "image_upload", "bytes": len(data)})
        return publishing.UploadedMedia(
            urn=f"urn:li:image:{uuid.uuid4().hex[:8]}", kind=MediaKind.IMAGE, alt_text=alt_text
        )

    def create_post(
        self,
        commentary: str,
        *,
        visibility: str = "PUBLIC",
        media: list[publishing.UploadedMedia] | None = None,
        idempotency_key: str = "",
    ) -> PublishedPost:
        if self._fail_with is not None:
            raise self._fail_with
        RecordingPublisher.calls.append(
            {
                "kind": "post",
                "commentary": commentary,
                "visibility": visibility,
                "media": [m.urn for m in (media or [])],
                "idempotency_key": idempotency_key,
            }
        )
        urn = f"urn:li:share:{len(RecordingPublisher.calls)}"
        return PublishedPost(urn=urn, url=publishing.post_url(urn))


@pytest.fixture
def publisher(monkeypatch: pytest.MonkeyPatch) -> type[RecordingPublisher]:
    RecordingPublisher.calls = []
    monkeypatch.setattr(worker.publishing, "build_publisher", lambda account: RecordingPublisher())
    return RecordingPublisher


@pytest.fixture
def failing_publisher(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    def _install(error: PublishingError) -> type[RecordingPublisher]:
        RecordingPublisher.calls = []
        monkeypatch.setattr(
            worker.publishing,
            "build_publisher",
            lambda account: RecordingPublisher(fail_with=error),
        )
        return RecordingPublisher

    return _install


@pytest.fixture
def configured(monkeypatch: pytest.MonkeyPatch) -> None:
    from pydantic import SecretStr

    from app.config import settings

    monkeypatch.setattr(settings, "linkedin_client_id", "test-client")
    monkeypatch.setattr(settings, "linkedin_client_secret", SecretStr("test-secret"))


# ── builders ─────────────────────────────────────────────────────────────────


def make_workspace(db: Session) -> Workspace:
    workspace = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
    db.add(workspace)
    db.flush()
    return workspace


def make_user(db: Session) -> User:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
    db.add(user)
    db.flush()
    return user


def make_account(db: Session, workspace: Workspace, *, granted: bool = True) -> LinkedInAccount:
    account = LinkedInAccount(
        workspace_id=workspace.id,
        label="Founder",
        full_name="Tushar Anand",
        status=LinkedInAccountStatus.ACTIVE,
        proxy=None,
    )
    if granted:
        account.publishing_token_ciphertext = encrypt_str("member-token")
        account.publishing_scopes = ["openid", POST_SCOPE]
        account.publishing_member_urn = "urn:li:person:abc"
        account.publishing_token_expires_at = datetime.now(UTC) + timedelta(days=30)
        account.publishing_authorized_at = datetime.now(UTC)
    db.add(account)
    db.flush()
    return account


def make_post(
    db: Session,
    workspace: Workspace,
    account: LinkedInAccount,
    user: User,
    *,
    status: PostStatus = PostStatus.SCHEDULED,
    scheduled_at: datetime | None = None,
    content: str = "Hello LinkedIn",
) -> LinkedInPost:
    post = LinkedInPost(
        workspace_id=workspace.id,
        created_by_id=user.id,
        linkedin_account_id=account.id,
        content=content,
        status=status,
        scheduled_at=scheduled_at if scheduled_at is not None else datetime.now(UTC),
        scheduled_timezone="UTC",
        media=[],
    )
    db.add(post)
    db.flush()
    return post


def notifications(db: Session, workspace: Workspace) -> list[Notification]:
    return [n for n in db.query(Notification).all() if n.workspace_id == workspace.id]


# ── the happy path ───────────────────────────────────────────────────────────


def test_publishes_and_records_the_linkedin_identifiers(
    sdb: Session, configured: None, publisher: type[RecordingPublisher]
) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    post = make_post(sdb, workspace, account, make_user(sdb))

    result = worker.publish_post(str(post.id))

    assert result == {"status": "published"}
    sdb.refresh(post)
    assert post.status is PostStatus.PUBLISHED
    assert post.published_at is not None
    assert post.linkedin_post_id == "urn:li:share:1"
    assert post.linkedin_url == "https://www.linkedin.com/feed/update/urn:li:share:1/"
    assert post.failure_reason == ""
    assert post.attempts == 1

    assert len(publisher.calls) == 1
    assert publisher.calls[0]["commentary"] == "Hello LinkedIn"
    # The claim's publish key travels upstream as an idempotency hint too.
    assert publisher.calls[0]["idempotency_key"]

    published = [n for n in notifications(sdb, workspace) if n.type.value == "post_published"]
    assert len(published) == 1


def test_uploads_media_before_posting_and_caches_the_urn(
    sdb: Session, configured: None, publisher: type[RecordingPublisher], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker.media_service, "download_sync", lambda asset: b"fake-bytes")

    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    user = make_user(sdb)
    post = make_post(sdb, workspace, account, user)

    asset = MediaAsset(
        workspace_id=workspace.id,
        uploaded_by_id=user.id,
        kind=MediaKind.IMAGE,
        filename="shot.png",
        content_type="image/png",
        size_bytes=10,
        storage_key=f"workspaces/{workspace.id}/media/shot.png",
    )
    sdb.add(asset)
    sdb.flush()
    link = LinkedInPostMedia(
        post_id=post.id, media_asset_id=asset.id, position=0, alt_text="A screenshot"
    )
    sdb.add(link)
    sdb.flush()
    # The worker runs on a fresh session in production; expire here so the
    # post's collection is re-read rather than served from the identity map.
    sdb.expire(post)

    worker.publish_post(str(post.id))

    kinds = [call["kind"] for call in publisher.calls]
    assert kinds == ["image_upload", "post"]
    assert publisher.calls[1]["media"] == [publisher.calls[1]["media"][0]]
    sdb.refresh(link)
    # Cached, so a later retry does not re-upload the same bytes.
    assert link.linkedin_asset_urn.startswith("urn:li:image:")


# ── duplicate prevention ─────────────────────────────────────────────────────


def test_redelivery_of_a_published_post_does_nothing(
    sdb: Session, configured: None, publisher: type[RecordingPublisher]
) -> None:
    """The broker's at-least-once delivery must not become at-least-twice posting."""
    workspace = make_workspace(sdb)
    post = make_post(sdb, workspace, make_account(sdb, workspace), make_user(sdb))

    first = worker.publish_post(str(post.id))
    second = worker.publish_post(str(post.id))
    third = worker.publish_post(str(post.id))

    assert first == {"status": "published"}
    assert second == {"status": "skipped"}
    assert third == {"status": "skipped"}
    assert len([c for c in publisher.calls if c["kind"] == "post"]) == 1

    sdb.refresh(post)
    assert post.attempts == 1


def test_a_post_already_being_published_is_not_published_again(
    sdb: Session, configured: None, publisher: type[RecordingPublisher]
) -> None:
    """Simulates the second of two concurrent workers arriving mid-flight."""
    workspace = make_workspace(sdb)
    post = make_post(
        sdb,
        workspace,
        make_account(sdb, workspace),
        make_user(sdb),
        status=PostStatus.PUBLISHING,
    )
    post.publishing_started_at = datetime.now(UTC)
    post.attempts = 1
    post.publish_key = LinkedInPost.build_publish_key(post.id, 1)
    sdb.flush()

    result = worker.publish_post(str(post.id))

    assert result == {"status": "skipped"}
    assert publisher.calls == []
    sdb.refresh(post)
    assert post.status is PostStatus.PUBLISHING


def test_cancelled_post_is_never_published(
    sdb: Session, configured: None, publisher: type[RecordingPublisher]
) -> None:
    workspace = make_workspace(sdb)
    post = make_post(
        sdb,
        workspace,
        make_account(sdb, workspace),
        make_user(sdb),
        status=PostStatus.CANCELLED,
    )

    assert worker.publish_post(str(post.id)) == {"status": "skipped"}
    assert publisher.calls == []


def test_a_post_not_yet_due_is_left_alone(
    sdb: Session, configured: None, publisher: type[RecordingPublisher]
) -> None:
    workspace = make_workspace(sdb)
    post = make_post(
        sdb,
        workspace,
        make_account(sdb, workspace),
        make_user(sdb),
        scheduled_at=datetime.now(UTC) + timedelta(hours=3),
    )

    assert worker.publish_post(str(post.id)) == {"status": "skipped"}
    assert publisher.calls == []
    sdb.refresh(post)
    assert post.status is PostStatus.SCHEDULED


def test_a_missing_post_is_not_an_error(sdb: Session, configured: None, publisher: type[RecordingPublisher]) -> None:
    assert worker.publish_post(str(uuid.uuid4())) == {"status": "skipped"}
    assert publisher.calls == []


# ── failure handling ─────────────────────────────────────────────────────────


def test_a_transient_failure_is_retried_with_backoff(
    sdb: Session, configured: None, failing_publisher: Any
) -> None:
    failing_publisher(
        PublishingError("LinkedIn is rate-limiting", code="rate_limited", retryable=True)
    )
    workspace = make_workspace(sdb)
    post = make_post(sdb, workspace, make_account(sdb, workspace), make_user(sdb))

    result = worker.publish_post(str(post.id))

    assert result["status"] == "scheduled"
    sdb.refresh(post)
    assert post.status is PostStatus.SCHEDULED
    assert post.attempts == 1
    assert post.scheduled_at > datetime.now(UTC)
    assert post.error_code == "rate_limited"
    # Not failed yet, so no failure notification has been raised.
    assert [n for n in notifications(sdb, workspace) if n.type.value == "post_failed"] == []


def test_retries_are_bounded(sdb: Session, configured: None, failing_publisher: Any) -> None:
    """Controlled retry: the system does not keep trying forever."""
    failing_publisher(PublishingError("upstream blip", code="http_503", retryable=True))
    workspace = make_workspace(sdb)
    post = make_post(sdb, workspace, make_account(sdb, workspace), make_user(sdb))

    for _ in range(worker.MAX_AUTO_ATTEMPTS + 2):
        # Pull each retry's slot back into the past so the next run is due.
        post.scheduled_at = datetime.now(UTC) - timedelta(seconds=1)
        sdb.flush()
        worker.publish_post(str(post.id))

    sdb.refresh(post)
    assert post.status is PostStatus.FAILED
    assert post.attempts == worker.MAX_AUTO_ATTEMPTS
    assert post.failure_reason == "upstream blip"


def test_a_permanent_failure_stops_immediately_and_notifies(
    sdb: Session, configured: None, failing_publisher: Any
) -> None:
    failing_publisher(
        PublishingError("LinkedIn rejected the content", code="unprocessable", request_id="req-42")
    )
    workspace = make_workspace(sdb)
    post = make_post(sdb, workspace, make_account(sdb, workspace), make_user(sdb))

    result = worker.publish_post(str(post.id))

    assert result["status"] == "failed"
    sdb.refresh(post)
    assert post.status is PostStatus.FAILED
    assert post.failure_reason == "LinkedIn rejected the content"
    assert post.error_code == "unprocessable"
    assert post.request_id == "req-42"
    assert post.failed_at is not None
    assert [n for n in notifications(sdb, workspace) if n.type.value == "post_failed"]


def test_lost_authorization_clears_the_grant_and_asks_for_a_reconnect(
    sdb: Session, configured: None, failing_publisher: Any
) -> None:
    failing_publisher(
        PublishingError("LinkedIn rejected the authorization", code="http_401", auth_lost=True)
    )
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    post = make_post(sdb, workspace, account, make_user(sdb))

    worker.publish_post(str(post.id))

    sdb.refresh(post)
    sdb.refresh(account)
    assert post.status is PostStatus.FAILED
    # The stale grant is forgotten, so the UI stops offering to publish with it.
    assert account.publishing_token_ciphertext is None
    assert account.publishing_scopes == []
    assert [
        n for n in notifications(sdb, workspace) if n.type.value == "publishing_auth_expired"
    ]


def test_an_expired_grant_fails_the_post_before_any_network_call(
    sdb: Session, configured: None, publisher: type[RecordingPublisher]
) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    account.publishing_token_expires_at = datetime.now(UTC) - timedelta(hours=1)
    sdb.flush()
    post = make_post(sdb, workspace, account, make_user(sdb))

    worker.publish_post(str(post.id))

    sdb.refresh(post)
    assert post.status is PostStatus.FAILED
    assert post.error_code == "expired"
    assert publisher.calls == []


def test_a_post_with_no_publishing_grant_is_never_sent(
    sdb: Session, configured: None, publisher: type[RecordingPublisher]
) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace, granted=False)
    post = make_post(sdb, workspace, account, make_user(sdb))

    worker.publish_post(str(post.id))

    sdb.refresh(post)
    assert post.status is PostStatus.FAILED
    assert post.error_code == "not_authorized"
    assert publisher.calls == []


def test_a_badly_overdue_post_is_failed_rather_than_published_late(
    sdb: Session, configured: None, publisher: type[RecordingPublisher]
) -> None:
    workspace = make_workspace(sdb)
    post = make_post(
        sdb,
        workspace,
        make_account(sdb, workspace),
        make_user(sdb),
        scheduled_at=datetime.now(UTC) - worker.MAX_LATENESS - timedelta(minutes=5),
    )

    worker.publish_post(str(post.id))

    sdb.refresh(post)
    assert post.status is PostStatus.FAILED
    assert post.error_code == "too_late"
    assert publisher.calls == []


def test_an_unexpected_exception_never_leaves_a_post_stuck_in_publishing(
    sdb: Session, configured: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(account: Any) -> Any:
        raise RuntimeError("something nobody predicted")

    monkeypatch.setattr(worker.publishing, "build_publisher", explode)
    workspace = make_workspace(sdb)
    post = make_post(sdb, workspace, make_account(sdb, workspace), make_user(sdb))

    result = worker.publish_post(str(post.id))

    assert result == {"status": "failed", "code": "unexpected_error"}
    sdb.refresh(post)
    assert post.status is PostStatus.FAILED


# ── the sweep ────────────────────────────────────────────────────────────────


def test_sweep_resolves_an_interrupted_publish_without_republishing(
    sdb: Session, configured: None, publisher: type[RecordingPublisher]
) -> None:
    """A worker that died mid-publish leaves a row we must not re-send."""
    workspace = make_workspace(sdb)
    post = make_post(
        sdb,
        workspace,
        make_account(sdb, workspace),
        make_user(sdb),
        status=PostStatus.PUBLISHING,
    )
    post.publishing_started_at = datetime.now(UTC) - worker.STUCK_AFTER - timedelta(minutes=1)
    post.attempts = 1
    sdb.flush()

    worker.sweep_due()

    sdb.refresh(post)
    assert post.status is PostStatus.FAILED
    assert post.error_code == "interrupted"
    assert "may already be live" in post.failure_reason
    assert publisher.calls == []
