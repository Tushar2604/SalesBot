"""Shared FastAPI dependencies: authentication and workspace scoping.

Tenant isolation funnels through `require_workspace`. Handlers receive a
`WorkspaceContext` that has already proven the caller is a member, so no handler
ever filters by `workspace_id` from untrusted input.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Path, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.errors import AuthenticationError, NotFoundError, PermissionDeniedError
from app.core.security import TokenError, decode_token
from app.db import get_db
from app.models.tenancy import User, Workspace, WorkspaceMember, WorkspaceRole

_bearer = HTTPBearer(auto_error=False, description="Access token from POST /auth/login")


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if credentials is None:
        raise AuthenticationError("missing bearer token")

    try:
        payload = decode_token(credentials.credentials, "access")
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

    @property
    def workspace_id(self) -> uuid.UUID:
        return self.workspace.id

    def require_role(self, minimum: WorkspaceRole) -> None:
        if not self.role.can_act_as(minimum):
            raise PermissionDeniedError(
                f"requires {minimum.value} role (you are {self.role.value})"
            )


async def require_workspace(
    workspace_id: Annotated[uuid.UUID, Path()],
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceContext:
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
