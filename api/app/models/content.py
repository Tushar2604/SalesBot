"""Content Studio: posts, their media, templates, and the publishing queue.

The invariant this schema exists to enforce: **a post is published at most once,
ever.** Publishing is not idempotent on LinkedIn's side in any way we control, so
the guarantee has to live here — in a status machine advanced under a row lock,
plus a UNIQUE publish key that a redelivered broker message cannot duplicate.

Everything is workspace-scoped and additionally pinned to one `LinkedInAccount`,
which is itself workspace-scoped: a post can only ever go out through an account
the same tenant owns.
"""

from __future__ import annotations

import enum
import hashlib
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class MediaKind(enum.StrEnum):
    """What LinkedIn will treat the attachment as.

    Deliberately narrow: these are the three attachment categories the documented
    Posts API accepts, so nothing here promises a capability that does not exist.
    """

    IMAGE = "image"
    VIDEO = "video"
    DOCUMENT = "document"


class PostStatus(enum.StrEnum):
    """Lifecycle of one post.

    `PUBLISHING` is a real persisted state, not a UI flourish: it is the claim
    that stops a second worker from picking the same row up mid-flight.
    """

    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {PostStatus.PUBLISHED, PostStatus.CANCELLED}

    @property
    def is_editable(self) -> bool:
        """Whether the composer may still change the content.

        A post that is mid-flight or already out is not editable: the copy in
        our database would stop matching the copy on LinkedIn.
        """
        return self in {
            PostStatus.DRAFT,
            PostStatus.PENDING_APPROVAL,
            PostStatus.APPROVED,
            PostStatus.SCHEDULED,
            PostStatus.FAILED,
            PostStatus.CANCELLED,
        }


class PostVisibility(enum.StrEnum):
    """Maps to the documented `visibility` field on the Posts API."""

    PUBLIC = "PUBLIC"
    CONNECTIONS = "CONNECTIONS"


class MediaAsset(UUIDPrimaryKey, Timestamps, Base):
    """One uploaded file in object storage, owned by a workspace.

    Storage is the S3/MinIO bucket the deployment already runs. The row holds the
    key, never the bytes; reads are served through short-lived presigned URLs so
    the bucket itself can stay private.
    """

    __tablename__ = "media_assets"
    __table_args__ = (Index("ix_media_assets_workspace_created", "workspace_id", "created_at"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    kind: Mapped[MediaKind] = mapped_column(
        Enum(MediaKind, name="media_kind", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    content_type: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Key within the configured bucket. Tenant-prefixed so a listing cannot
    # cross a workspace boundary even by accident.
    storage_key: Mapped[str] = mapped_column(String(400), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )


class LinkedInPost(UUIDPrimaryKey, Timestamps, Base):
    """A post composed in the Studio, in one of the `PostStatus` states."""

    __tablename__ = "linkedin_posts"
    __table_args__ = (
        # The double-publish guard. Written at the moment a post is claimed for
        # publishing; a redelivered task computing the same key collides instead
        # of producing a second post on LinkedIn.
        UniqueConstraint("publish_key", name="uq_linkedin_posts_publish_key"),
        Index("ix_linkedin_posts_workspace_status", "workspace_id", "status"),
        # The sweep's hot query: posts due for publishing.
        Index("ix_linkedin_posts_due", "status", "scheduled_at"),
        Index("ix_linkedin_posts_account", "linkedin_account_id"),
        Index("ix_linkedin_posts_workspace_created", "workspace_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    linkedin_account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("linkedin_accounts.id", ondelete="CASCADE"), nullable=False
    )

    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    visibility: Mapped[PostVisibility] = mapped_column(
        Enum(
            PostVisibility,
            name="post_visibility",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=PostVisibility.PUBLIC,
    )
    status: Mapped[PostStatus] = mapped_column(
        Enum(PostStatus, name="post_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=PostStatus.DRAFT,
    )

    # ── scheduling ───────────────────────────────────────────────────────────
    # Always UTC. The IANA zone the user picked is stored beside it so the UI can
    # render "9:30 AM Asia/Kolkata" a year later even if their profile zone moved.
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    scheduled_timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # Position within the workspace's publishing queue, when queued.
    queue_position: Mapped[int | None] = mapped_column(Integer)

    # ── publishing outcome ───────────────────────────────────────────────────
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    linkedin_post_id: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    linkedin_url: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    # Null until a publish is claimed, so drafts do not contend on the UNIQUE.
    publish_key: Mapped[str | None] = mapped_column(String(64))
    publishing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── failure state ────────────────────────────────────────────────────────
    failure_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_code: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    # LinkedIn echoes x-li-uuid / x-restli-id on failures; keeping it is what
    # makes a support conversation with LinkedIn possible at all.
    request_id: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── approval workflow (off unless the workspace enables it) ───────────────
    submitted_for_approval_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Cached analytics, only ever written from a real upstream read.
    analytics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    analytics_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    media: Mapped[list[LinkedInPostMedia]] = relationship(
        back_populates="post",
        cascade="all, delete-orphan",
        order_by="LinkedInPostMedia.position",
        lazy="selectin",
    )

    @staticmethod
    def build_publish_key(post_id: uuid.UUID | str, attempt: int) -> str:
        """Unique per (post, attempt).

        The attempt is part of the key on purpose: a *deliberate* retry after a
        failure must be allowed, while a redelivery of the same in-flight task
        must not. Attempts only advance under the row lock.
        """
        return hashlib.sha256(f"post:{post_id}:{attempt}".encode()).hexdigest()


class LinkedInPostMedia(UUIDPrimaryKey, Base):
    """Join of a post to one uploaded asset, in display order."""

    __tablename__ = "linkedin_post_media"
    __table_args__ = (
        UniqueConstraint("post_id", "position", name="uq_linkedin_post_media_position"),
        Index("ix_linkedin_post_media_post", "post_id"),
    )

    post_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("linkedin_posts.id", ondelete="CASCADE"), nullable=False
    )
    media_asset_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alt_text: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    # The URN LinkedIn assigned when the asset was registered for this post.
    # Cached so a retry does not re-upload bytes that already landed.
    linkedin_asset_urn: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    post: Mapped[LinkedInPost] = relationship(back_populates="media")
    asset: Mapped[MediaAsset] = relationship(lazy="selectin")


class PostTemplate(UUIDPrimaryKey, Timestamps, Base):
    """Reusable post copy, scoped to a workspace."""

    __tablename__ = "post_templates"
    __table_args__ = (Index("ix_post_templates_workspace", "workspace_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Asset ids carried along with the copy. A plain list rather than a join
    # table: templates are small, and the assets are already rows of their own.
    media_asset_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)


class PostQueue(UUIDPrimaryKey, Timestamps, Base):
    """A workspace's recurring publishing slots.

    The queue does not publish anything itself. It is a slot generator: adding a
    post to the queue resolves the next free slot and writes an ordinary
    `scheduled_at`, so there is exactly one scheduling mechanism in the system.
    """

    __tablename__ = "post_queues"
    __table_args__ = (UniqueConstraint("workspace_id", name="uq_post_queues_workspace"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    # [{"weekday": 0-6, "time": "09:00"}], ordered. Weekday 0 is Monday.
    slots: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
