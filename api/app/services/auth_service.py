"""Signup, login, refresh-token rotation, logout."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import AuthenticationError, ConflictError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.core.utils import unique_slug
from app.models.tenancy import RefreshSession, User, Workspace, WorkspaceMember, WorkspaceRole
from app.services import audit


async def _existing_slugs(db: AsyncSession, base: str) -> set[str]:
    stmt = select(Workspace.slug).where(Workspace.slug.like(f"{base}%"))
    return set((await db.execute(stmt)).scalars().all())


async def create_workspace_for_user(
    db: AsyncSession, user: User, name: str, *, role: WorkspaceRole = WorkspaceRole.OWNER
) -> Workspace:
    from app.core.utils import slugify

    base = slugify(name)
    workspace = Workspace(
        name=name.strip(), slug=unique_slug(name, taken=await _existing_slugs(db, base))
    )
    db.add(workspace)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role=role))
    await db.flush()
    return workspace


async def signup(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    full_name: str,
    workspace_name: str,
    ip_address: str = "",
    user_agent: str = "",
) -> tuple[User, Workspace, str, str]:
    """Creates user + their first workspace. Returns (user, workspace, access, refresh)."""
    normalized = email.strip().lower()

    exists = await db.scalar(select(func.count()).select_from(User).where(User.email == normalized))
    if exists:
        raise ConflictError("an account with that email already exists")

    user = User(
        email=normalized,
        password_hash=hash_password(password),
        full_name=full_name.strip(),
        last_login_at=datetime.now(UTC),
    )
    db.add(user)
    await db.flush()

    workspace = await create_workspace_for_user(
        db, user, workspace_name.strip() or f"{full_name or normalized.split('@')[0]}'s workspace"
    )

    access = create_access_token(user.id, workspace.id)
    refresh = await issue_refresh_session(db, user, ip_address=ip_address, user_agent=user_agent)

    await audit.record(
        db,
        "user.signup",
        workspace_id=workspace.id,
        actor_user_id=user.id,
        target_type="user",
        target_id=user.id,
        ip_address=ip_address,
    )
    return user, workspace, access, refresh


async def issue_refresh_session(
    db: AsyncSession, user: User, *, ip_address: str = "", user_agent: str = ""
) -> str:
    token, jti, expires_at = create_refresh_token(user.id)
    db.add(
        RefreshSession(
            user_id=user.id,
            jti=jti,
            expires_at=expires_at,
            ip_address=ip_address[:64],
            user_agent=user_agent[:400],
        )
    )
    await db.flush()
    return token


async def login(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    ip_address: str = "",
    user_agent: str = "",
) -> tuple[User, str, str]:
    normalized = email.strip().lower()
    user = (await db.execute(select(User).where(User.email == normalized))).scalar_one_or_none()

    # Same error for unknown email and wrong password — no account enumeration.
    if user is None or not verify_password(password, user.password_hash):
        raise AuthenticationError("invalid email or password")
    if not user.is_active:
        raise AuthenticationError("account is deactivated")

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    user.last_login_at = datetime.now(UTC)

    default_workspace_id = await db.scalar(
        select(WorkspaceMember.workspace_id)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(WorkspaceMember.created_at)
        .limit(1)
    )

    access = create_access_token(user.id, default_workspace_id)
    refresh = await issue_refresh_session(db, user, ip_address=ip_address, user_agent=user_agent)

    await audit.record(
        db,
        "user.login",
        workspace_id=default_workspace_id,
        actor_user_id=user.id,
        target_type="user",
        target_id=user.id,
        ip_address=ip_address,
    )
    return user, access, refresh


async def _revoke_family(db: AsyncSession, user_id: uuid.UUID) -> None:
    sessions = (
        await db.execute(
            select(RefreshSession).where(
                RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None)
            )
        )
    ).scalars()
    now = datetime.now(UTC)
    for session in sessions:
        session.revoked_at = now


async def rotate_refresh(
    db: AsyncSession, refresh_token: str, *, ip_address: str = "", user_agent: str = ""
) -> tuple[User, str, str]:
    """Validates and rotates a refresh token.

    Reuse of an already-revoked token is treated as theft: every session for
    that user is revoked, forcing a fresh login on all devices.
    """
    from app.core.security import TokenError, decode_token

    try:
        payload = decode_token(refresh_token, "refresh")
    except TokenError as exc:
        raise AuthenticationError(str(exc)) from exc

    jti = payload["jti"]
    user_id = uuid.UUID(payload["sub"])

    session = (
        await db.execute(select(RefreshSession).where(RefreshSession.jti == jti))
    ).scalar_one_or_none()

    if session is None:
        raise AuthenticationError("unknown session")

    if session.revoked_at is not None:
        await _revoke_family(db, user_id)
        await audit.record(
            db,
            "auth.refresh_reuse_detected",
            actor_user_id=user_id,
            target_type="refresh_session",
            target_id=session.id,
            ip_address=ip_address,
            note="revoked all sessions for this user",
        )
        raise AuthenticationError("session revoked; please sign in again")

    if session.expires_at <= datetime.now(UTC):
        raise AuthenticationError("session expired")

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("user not found or deactivated")

    session.revoked_at = datetime.now(UTC)

    default_workspace_id = await db.scalar(
        select(WorkspaceMember.workspace_id)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(WorkspaceMember.created_at)
        .limit(1)
    )
    access = create_access_token(user.id, default_workspace_id)
    new_refresh = await issue_refresh_session(
        db, user, ip_address=ip_address, user_agent=user_agent
    )
    return user, access, new_refresh


async def logout(db: AsyncSession, refresh_token: str | None) -> None:
    """Idempotent: an absent or already-invalid token still yields a clean logout."""
    if not refresh_token:
        return
    from app.core.security import TokenError, decode_token

    try:
        payload = decode_token(refresh_token, "refresh")
    except TokenError:
        return

    session = (
        await db.execute(select(RefreshSession).where(RefreshSession.jti == payload["jti"]))
    ).scalar_one_or_none()
    if session is not None and session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)


def access_token_ttl_seconds() -> int:
    return settings.access_token_ttl_minutes * 60
