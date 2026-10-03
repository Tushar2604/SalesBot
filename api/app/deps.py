"""Shared FastAPI dependencies: authentication and workspace scoping.

Tenant isolation funnels through `require_workspace`. Handlers receive a
`WorkspaceContext` that has already proven the caller is a member, so no handler
ever filters by `workspace_id` from untrusted input.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Depends, Header, Path, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import (
    AuthenticationError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitedError,
)
from app.core.security import TokenError, decode_token
from app.db import get_db
from app.integrations import api_keys
from app.models.integrations import ApiKey
from app.models.tenancy import User, Workspace, WorkspaceMember, WorkspaceRole

_bearer = HTTPBearer(
    auto_error=False,
    description="Access token from POST /auth/login, or an API key (sr_live_...)",
)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if credentials is None:
        raise AuthenticationError("missing bearer token")
    return await _user_from_token(credentials.credentials, db)


async def _user_from_token(token: str, db: AsyncSession) -> User:
    if api_keys.looks_like_key(token):
        # Keys are scoped to one workspace; account-level endpoints (profile,
        # workspace list, sign-out) need a person's own login.
        raise AuthenticationError("API keys work on /workspaces/{workspace_id}/... endpoints only")
    try:
        payload = decode_token(token, "access")
    except TokenError as exc:
        raise AuthenticationError(str(exc)) from exc

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("malformed token subject") from exc

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("user not found or deactivated")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


@dataclass(slots=True)
class WorkspaceContext:
    """Proven membership. Carry this, never a raw workspace_id from the client."""

    workspace: Workspace
    user: User
    role: WorkspaceRole
    # Set when the request authenticated with an API key rather than a login.
    api_key_id: uuid.UUID | None = None

    @property
    def workspace_id(self) -> uuid.UUID:
        return self.workspace.id

    @property
    def via_api_key(self) -> bool:
        return self.api_key_id is not None

    def require_login(self) -> None:
        """For actions an integration must never take, like minting or
        revoking API keys: a stolen key can't be used to make more keys."""
        if self.via_api_key:
            raise PermissionDeniedError("this action needs a signed-in person, not an API key")

    def require_role(self, minimum: WorkspaceRole) -> None:
        if not self.role.can_act_as(minimum):
            raise PermissionDeniedError(
                f"requires {minimum.value} role (you are {self.role.value})"
            )


async def require_workspace(
    workspace_id: Annotated[uuid.UUID, Path()],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
    x_api_key: Annotated[
        str | None,
        Header(description="API key, for tools that can't set an Authorization header"),
    ] = None,
) -> WorkspaceContext:
    token = credentials.credentials if credentials is not None else (x_api_key or "")
    if not token:
        raise AuthenticationError("missing bearer token or X-API-Key header")
    if api_keys.looks_like_key(token):
        return await _workspace_from_api_key(workspace_id, token, db)
    user = await _user_from_token(token, db)

    stmt = (
        select(WorkspaceMember)
        .options(selectinload(WorkspaceMember.workspace))
        .where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    membership = (await db.execute(stmt)).scalar_one_or_none()

    # A non-member gets 404, not 403: existence of another tenant's workspace is
    # not something an outsider should be able to probe.
    if membership is None or membership.workspace.deleted_at is not None:
        raise NotFoundError("workspace not found")

    return WorkspaceContext(workspace=membership.workspace, user=user, role=membership.role)


# Refresh last_used_at at most this often, so a busy integration isn't a
# write on every request.
_LAST_USED_RESOLUTION = timedelta(minutes=1)


async def _workspace_from_api_key(
    workspace_id: uuid.UUID, token: str, db: AsyncSession
) -> WorkspaceContext:
    key = (
        await db.execute(select(ApiKey).where(ApiKey.key_hash == api_keys.hash_key(token)))
    ).scalar_one_or_none()
    if key is None or key.revoked_at is not None:
        raise AuthenticationError("invalid or revoked API key")
    if key.workspace_id != workspace_id:
        # Same answer as for a non-member: don't confirm other workspaces exist.
        raise NotFoundError("workspace not found")

    membership = (
        await db.execute(
            select(WorkspaceMember)
            .options(selectinload(WorkspaceMember.workspace))
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == key.created_by_id,
            )
        )
    ).scalar_one_or_none()
    user = await db.get(User, key.created_by_id)
    if (
        membership is None
        or membership.workspace.deleted_at is not None
        or user is None
        or not user.is_active
    ):
        raise AuthenticationError(
            "this API key's creator is no longer in the workspace; create a new key"
        )

    if await api_keys.over_rate_limit(key.id):
        raise RateLimitedError("too many requests for this API key; wait a minute and try again")

    now = datetime.now(UTC)
    if key.last_used_at is None or now - key.last_used_at > _LAST_USED_RESOLUTION:
        key.last_used_at = now

    # Never more than the person who made the key can do today.
    role = key.role if membership.role.can_act_as(key.role) else membership.role
    return WorkspaceContext(workspace=membership.workspace, user=user, role=role, api_key_id=key.id)


Workspace_ = Annotated[WorkspaceContext, Depends(require_workspace)]


def require_role(minimum: WorkspaceRole):  # type: ignore[no-untyped-def]
    """Route-level guard: `dependencies=[Depends(require_role(WorkspaceRole.ADMIN))]`."""

    async def _guard(ctx: Workspace_) -> WorkspaceContext:
        ctx.require_role(minimum)
        return ctx

    return _guard


RequireAdmin = Annotated[WorkspaceContext, Depends(require_role(WorkspaceRole.ADMIN))]
RequireOwner = Annotated[WorkspaceContext, Depends(require_role(WorkspaceRole.OWNER))]


def client_ip(request: Request) -> str:
    """Best-effort client IP. Trusts X-Forwarded-For only behind our own proxy."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]
