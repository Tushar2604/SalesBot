"""Users, workspaces, membership, invites, sessions, audit trail.

Tenancy model: every tenant-owned row carries `workspace_id`. Access is scoped
in one place — the `require_workspace` dependency — which resolves the caller's
membership and hands handlers a `WorkspaceContext`. Postgres RLS policies are
layered on top of the tenant *data* tables (Phase 2+) as defence in depth; the
tables in this module are deliberately exempt because they are queried before a
workspace is known (login, "list my workspaces", accepting an invite).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class WorkspaceRole(enum.StrEnum):
    """Role names match SalesRobot's team tiers.

    owner  — billing + destructive actions + everything below
    admin  — manage accounts, campaigns, members; cannot delete workspace or change billing
    member — operate own campaigns and inbox; read-only on workspace settings
    """

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"

    @property
    def rank(self) -> int:
        return {"member": 0, "admin": 1, "owner": 2}[self.value]

    def can_act_as(self, required: WorkspaceRole) -> bool:
        return self.rank >= required.rank


class InviteStatus(enum.StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"


class User(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")

    memberships: Mapped[list[WorkspaceMember]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class Workspace(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "workspaces"

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    # Soft-delete so an accidental deletion never destroys outreach history.
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Workspace-wide kill switch: when true the dispatcher refuses to emit any
    # LinkedIn or email action for this tenant, regardless of campaign state.
    outreach_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    members: Mapped[list[WorkspaceMember]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )


class WorkspaceMember(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "workspace_members"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_members_workspace_user"),
        Index("ix_workspace_members_user_id", "user_id"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[WorkspaceRole] = mapped_column(
        Enum(WorkspaceRole, name="workspace_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=WorkspaceRole.MEMBER,
    )

    workspace: Mapped[Workspace] = relationship(back_populates="members")
    user: Mapped[User] = relationship(back_populates="memberships")


class WorkspaceInvite(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "workspace_invites"
    __table_args__ = (Index("ix_workspace_invites_workspace_email", "workspace_id", "email"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[WorkspaceRole] = mapped_column(
        Enum(WorkspaceRole, name="workspace_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=WorkspaceRole.MEMBER,
    )
    # Only the hash is stored; the raw token exists solely in the invite link.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    status: Mapped[InviteStatus] = mapped_column(
        Enum(InviteStatus, name="invite_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=InviteStatus.PENDING,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invited_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RefreshSession(UUIDPrimaryKey, Timestamps, Base):
    """One row per issued refresh token, so logout and rotation can revoke.

    Rotation reuse is treated as theft: presenting a `revoked` jti revokes the
    entire family for that user.
    """

    __tablename__ = "refresh_sessions"
    __table_args__ = (Index("ix_refresh_sessions_user_id", "user_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    jti: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False, default="")

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > datetime.now(self.expires_at.tzinfo)


class NotificationType(enum.StrEnum):
    INBOX_REPLY = "inbox_reply"
    ACCOUNT_ACTION_NEEDED = "account_action_needed"
    MEMBER_JOINED = "member_joined"
    CAMPAIGN_COMPLETED = "campaign_completed"
    INVITE_UPDATE = "invite_update"
    # Content Studio
    POST_SCHEDULED = "post_scheduled"
    POST_PUBLISHED = "post_published"
    POST_FAILED = "post_failed"
    POST_NEEDS_APPROVAL = "post_needs_approval"
    POST_APPROVED = "post_approved"
    PUBLISHING_AUTH_EXPIRED = "publishing_auth_expired"


class Notification(UUIDPrimaryKey, Base):
    """Workspace-wide feed behind the bell icon.

    Shared across members (one row per event, not one per recipient) since
    every notification so far is workspace-scoped, not personal. Read state
    is tracked per user in `read_by` rather than a join table — the expected
    row count per workspace is small enough that this stays cheap to query.
    """

    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_workspace_created", "workspace_id", "created_at"),)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[NotificationType] = mapped_column(
        Enum(
            NotificationType,
            name="notification_type",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    link: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    read_by: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)


class AuditEvent(UUIDPrimaryKey, Base):
    """Append-only trail. Never updated, never deleted by application code."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_workspace_created", "workspace_id", "created_at"),
        Index("ix_audit_events_actor", "actor_user_id"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    target_id: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    ip_address: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
