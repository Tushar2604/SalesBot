"""Workspace membership and invitations."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.errors import (
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationFailedError,
)
from app.core.security import hash_password
from app.core.utils import generate_token, hash_token
from app.models.tenancy import (
    InviteStatus,
    NotificationType,
    User,
    Workspace,
    WorkspaceInvite,
    WorkspaceMember,
    WorkspaceRole,
)
from app.services import audit, notification_service

INVITE_TTL_DAYS = 14


async def list_members(db: AsyncSession, workspace_id: uuid.UUID) -> list[WorkspaceMember]:
    stmt = (
        select(WorkspaceMember)
        .options(selectinload(WorkspaceMember.user))
        .where(WorkspaceMember.workspace_id == workspace_id)
        .order_by(WorkspaceMember.created_at)
    )
    return list((await db.execute(stmt)).scalars().all())


async def _count_owners(db: AsyncSession, workspace_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            select(func.count())
            .select_from(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.role == WorkspaceRole.OWNER,
            )
        )
        or 0
    )


async def update_member_role(
    db: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    member_id: uuid.UUID,
    new_role: WorkspaceRole,
    actor: User,
) -> WorkspaceMember:
    member = (
        await db.execute(
            select(WorkspaceMember)
            .options(selectinload(WorkspaceMember.user))
            .where(
                WorkspaceMember.id == member_id,
                WorkspaceMember.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise NotFoundError("member not found")

    # A workspace must always retain at least one owner, or billing and
    # destructive actions become permanently unreachable.
    demoting_an_owner = member.role is WorkspaceRole.OWNER and new_role is not WorkspaceRole.OWNER
    if demoting_an_owner and await _count_owners(db, workspace_id) <= 1:
        raise ConflictError("workspace must have at least one owner")

    previous = member.role
    member.role = new_role
    await audit.record(
        db,
        "workspace.member_role_changed",
        workspace_id=workspace_id,
        actor_user_id=actor.id,
        target_type="workspace_member",
        target_id=member.id,
        metadata={"from": previous.value, "to": new_role.value},
    )
    return member


async def remove_member(
    db: AsyncSession, *, workspace_id: uuid.UUID, member_id: uuid.UUID, actor: User
) -> None:
    member = (
        await db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.id == member_id,
                WorkspaceMember.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if member is None:
        raise NotFoundError("member not found")

    if member.role is WorkspaceRole.OWNER and await _count_owners(db, workspace_id) <= 1:
        raise ConflictError("cannot remove the last owner")

    await db.delete(member)
    await audit.record(
        db,
        "workspace.member_removed",
        workspace_id=workspace_id,
        actor_user_id=actor.id,
        target_type="workspace_member",
        target_id=member_id,
    )


async def create_invite(
    db: AsyncSession,
    *,
    workspace: Workspace,
    email: str,
    role: WorkspaceRole,
    actor: User,
    actor_role: WorkspaceRole,
) -> tuple[WorkspaceInvite, str]:
    """Returns (invite, raw_token). The raw token is never persisted or shown again."""
    normalized = email.strip().lower()

    # An admin must not be able to mint an owner and take over billing.
    if role is WorkspaceRole.OWNER and actor_role is not WorkspaceRole.OWNER:
        raise PermissionDeniedError("only an owner can invite another owner")

    already_member = await db.scalar(
        select(func.count())
        .select_from(WorkspaceMember)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == workspace.id, User.email == normalized)
    )
    if already_member:
        raise ConflictError("that person is already a member of this workspace")

    pending = (
        (
            await db.execute(
                select(WorkspaceInvite).where(
                    WorkspaceInvite.workspace_id == workspace.id,
                    WorkspaceInvite.email == normalized,
                    WorkspaceInvite.status == InviteStatus.PENDING,
                )
            )
        )
        .scalars()
        .all()
    )
    # Re-inviting supersedes the old link rather than erroring.
    for stale in pending:
        stale.status = InviteStatus.REVOKED

    raw_token = generate_token()
    invite = WorkspaceInvite(
        workspace_id=workspace.id,
        email=normalized,
        role=role,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(days=INVITE_TTL_DAYS),
        invited_by_id=actor.id,
    )
    db.add(invite)
    await db.flush()

    await audit.record(
        db,
        "workspace.invite_created",
        workspace_id=workspace.id,
        actor_user_id=actor.id,
        target_type="workspace_invite",
        target_id=invite.id,
        metadata={"email": normalized, "role": role.value},
    )
    return invite, raw_token


def invite_url(raw_token: str) -> str:
    return f"{settings.web_base_url.rstrip('/')}/invite/{raw_token}"


async def list_invites(db: AsyncSession, workspace_id: uuid.UUID) -> list[WorkspaceInvite]:
    stmt = (
        select(WorkspaceInvite)
        .where(WorkspaceInvite.workspace_id == workspace_id)
        .order_by(WorkspaceInvite.created_at.desc())
    )
    return list((await db.execute(stmt)).scalars().all())


async def revoke_invite(
    db: AsyncSession, *, workspace_id: uuid.UUID, invite_id: uuid.UUID, actor: User
) -> None:
    invite = (
        await db.execute(
            select(WorkspaceInvite).where(
                WorkspaceInvite.id == invite_id,
                WorkspaceInvite.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if invite is None:
        raise NotFoundError("invite not found")
    if invite.status is not InviteStatus.PENDING:
        raise ConflictError(f"invite is already {invite.status.value}")

    invite.status = InviteStatus.REVOKED
    await audit.record(
        db,
        "workspace.invite_revoked",
        workspace_id=workspace_id,
        actor_user_id=actor.id,
        target_type="workspace_invite",
        target_id=invite.id,
    )


async def accept_invite(
    db: AsyncSession,
    *,
    token: str,
    password: str | None,
    full_name: str,
    current_user: User | None = None,
) -> tuple[User, Workspace, bool]:
    """Accepts an invite, creating the user when they have no account yet.

    Returns (user, workspace, created_user).
    """
    invite = (
        await db.execute(
            select(WorkspaceInvite).where(WorkspaceInvite.token_hash == hash_token(token))
        )
    ).scalar_one_or_none()

    if invite is None:
        raise NotFoundError("invite not found")
    if invite.status is not InviteStatus.PENDING:
        raise ConflictError(f"invite is already {invite.status.value}")
    if invite.expires_at <= datetime.now(UTC):
        invite.status = InviteStatus.EXPIRED
        raise ConflictError("invite has expired")

    user = current_user
    created = False

    if user is None:
        user = (
            await db.execute(select(User).where(User.email == invite.email))
        ).scalar_one_or_none()

    if user is None:
        if not password:
            raise ValidationFailedError("a password is required to create your account")
        user = User(
            email=invite.email,
            password_hash=hash_password(password),
            full_name=full_name.strip(),
            email_verified_at=datetime.now(UTC),  # the invite link proves control of the inbox
        )
        db.add(user)
        await db.flush()
        created = True
    elif user.email != invite.email:
        raise PermissionDeniedError("this invite was issued to a different email address")

    workspace = await db.get(Workspace, invite.workspace_id)
    if workspace is None or workspace.deleted_at is not None:
        raise NotFoundError("workspace no longer exists")

    existing = await db.scalar(
        select(func.count())
        .select_from(WorkspaceMember)
        .where(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if not existing:
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=invite.role))

    invite.status = InviteStatus.ACCEPTED
    invite.accepted_at = datetime.now(UTC)

    await audit.record(
        db,
        "workspace.invite_accepted",
        workspace_id=workspace.id,
        actor_user_id=user.id,
        target_type="workspace_invite",
        target_id=invite.id,
        metadata={"created_user": created},
    )
    if not existing:
        await notification_service.create(
            db,
            workspace.id,
            NotificationType.MEMBER_JOINED,
            f"{user.full_name or user.email} joined the workspace",
            body=f"Role: {invite.role.value}",
            link="/team",
        )
    return user, workspace, created
