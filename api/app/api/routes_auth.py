"""Authentication endpoints.

The refresh token is delivered as an httpOnly, SameSite=Lax cookie scoped to the
auth route prefix, so page scripts cannot read it and it is not attached to
unrelated cross-site requests. The access token lives in memory on the client.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api import API_V1_PREFIX
from app.config import settings
from app.core.errors import AuthenticationError
from app.db import get_db
from app.deps import CurrentUser, client_ip
from app.models.tenancy import WorkspaceMember
from app.schemas.auth import (
    InviteAcceptRequest,
    LoginRequest,
    MembershipResponse,
    MeResponse,
    SignupRequest,
    TokenResponse,
    UserResponse,
    WorkspaceResponse,
)
from app.services import auth_service, workspace_service

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE = "salesrobo_refresh"
# Must match where the auth router is actually mounted, or the browser will
# never attach the cookie to /auth/refresh.
_COOKIE_PATH = f"{API_V1_PREFIX}/auth"


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_ttl_days * 86400,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        path=_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path=_COOKIE_PATH)


@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(
    payload: SignupRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    _user, _workspace, access, refresh = await auth_service.signup(
        db,
        email=payload.email,
        password=payload.password,
        full_name=payload.full_name,
        workspace_name=payload.workspace_name,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent", ""),
    )
    _set_refresh_cookie(response, refresh)
    return TokenResponse(access_token=access, expires_in=auth_service.access_token_ttl_seconds())


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    _user, access, refresh = await auth_service.login(
        db,
        email=payload.email,
        password=payload.password,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent", ""),
    )
    _set_refresh_cookie(response, refresh)
    return TokenResponse(access_token=access, expires_in=auth_service.access_token_ttl_seconds())


@router.post("/refresh", response_model=TokenResponse)
async def refresh_tokens(
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    salesrobo_refresh: Annotated[str | None, Cookie()] = None,
) -> TokenResponse:
    if not salesrobo_refresh:
        raise AuthenticationError("no refresh session")

    _user, access, new_refresh = await auth_service.rotate_refresh(
        db,
        salesrobo_refresh,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent", ""),
    )
    _set_refresh_cookie(response, new_refresh)
    return TokenResponse(access_token=access, expires_in=auth_service.access_token_ttl_seconds())


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    salesrobo_refresh: Annotated[str | None, Cookie()] = None,
) -> Response:
    await auth_service.logout(db, salesrobo_refresh)
    _clear_refresh_cookie(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser, db: Annotated[AsyncSession, Depends(get_db)]) -> MeResponse:
    stmt = (
        select(WorkspaceMember)
        .options(selectinload(WorkspaceMember.workspace))
        .where(WorkspaceMember.user_id == user.id)
        .order_by(WorkspaceMember.created_at)
    )
    memberships = (await db.execute(stmt)).scalars().all()
    return MeResponse(
        user=UserResponse.model_validate(user),
        workspaces=[
            MembershipResponse(workspace=WorkspaceResponse.model_validate(m.workspace), role=m.role)
            for m in memberships
            if m.workspace.deleted_at is None
        ],
    )


@router.post("/accept-invite", response_model=TokenResponse)
async def accept_invite(
    payload: InviteAcceptRequest,
    request: Request,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TokenResponse:
    """Accepts a workspace invite. Works for both new and existing users.

    Unauthenticated on purpose: the invite token is the credential. An already
    signed-in user can call it too — the email must match the invite.
    """
    user, workspace, _created = await workspace_service.accept_invite(
        db,
        token=payload.token,
        password=payload.password,
        full_name=payload.full_name,
    )
    from app.core.security import create_access_token

    access = create_access_token(user.id, workspace.id)
    refresh = await auth_service.issue_refresh_session(
        db,
        user,
        ip_address=client_ip(request),
        user_agent=request.headers.get("user-agent", ""),
    )
    _set_refresh_cookie(response, refresh)
    return TokenResponse(access_token=access, expires_in=auth_service.access_token_ttl_seconds())
