"""LinkedIn account and proxy endpoints.

Connecting is asynchronous by necessity: the sign-in has to happen from the
account's assigned proxy, in a worker. These handlers persist intent, commit,
then enqueue — committing first, because a worker that starts before the row is
visible would find nothing.
"""

from __future__ import annotations

import uuid
from typing import Annotated
from urllib.parse import urlencode

import anyio
from fastapi import APIRouter, Depends, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.crypto import encrypt_str
from app.core.errors import ConflictError, NotFoundError, ValidationFailedError
from app.db import get_db
from app.deps import Workspace_
from app.linkedin import publishing
from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus, Proxy
from app.models.tenancy import WorkspaceRole
from app.schemas.linkedin import (
    CapsUpdateRequest,
    ChallengeSubmitRequest,
    ConnectResponse,
    CookieConnectRequest,
    CredentialsConnectRequest,
    LinkedInAccountResponse,
    ProxyCreateRequest,
    ProxyResponse,
    PublishingAuthorizeResponse,
)
from app.services import audit, linkedin_service
from app.worker.celery_app import celery_app

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["linkedin"])


def _respond(account: LinkedInAccount) -> ConnectResponse:
    next_step, message = linkedin_service.next_step_for(account)
    return ConnectResponse(
        account=linkedin_service.to_response(account), next_step=next_step, message=message
    )


# ── accounts ─────────────────────────────────────────────────────────────────


@router.get("/linkedin-accounts", response_model=list[LinkedInAccountResponse])
async def list_accounts(
    ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[LinkedInAccountResponse]:
    accounts = await linkedin_service.list_accounts(db, ctx.workspace_id)
    return [linkedin_service.to_response(a) for a in accounts]


@router.get("/linkedin-accounts/{account_id}", response_model=LinkedInAccountResponse)
async def get_account(
    account_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> LinkedInAccountResponse:
    account = await linkedin_service.get_account(db, ctx.workspace_id, account_id)
    return linkedin_service.to_response(account)


@router.post(
    "/linkedin-accounts/connect/cookie",
    response_model=ConnectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def connect_with_cookie(
    payload: CookieConnectRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConnectResponse:
    """Connect by pasting the `li_at` cookie from your own browser."""
    ctx.require_role(WorkspaceRole.ADMIN)

    account = await linkedin_service.create_account(
        db,
        ctx,
        label=payload.label,
        login_email="",
        timezone=payload.timezone,
        proxy_id=payload.proxy_id,
        reconnect_account_id=payload.account_id,
    )
    sealed = linkedin_service.seal_for_transit(
        {"li_at": payload.li_at, "jsessionid": payload.jsessionid or ""}
    )

    # Commit before enqueueing: the worker must be able to see this row.
    await db.commit()
    celery_app.send_task(
        "linkedin.auth.connect_cookie", args=[str(account.id), sealed], queue="linkedin.action"
    )
    return _respond(account)


@router.post(
    "/linkedin-accounts/connect/credentials",
    response_model=ConnectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def connect_with_credentials(
    payload: CredentialsConnectRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConnectResponse:
    """Connect with email and password. LinkedIn may then ask for a code."""
    ctx.require_role(WorkspaceRole.ADMIN)

    account = await linkedin_service.create_account(
        db,
        ctx,
        label=payload.label,
        login_email=str(payload.email),
        timezone=payload.timezone,
        proxy_id=payload.proxy_id,
    )
    sealed = linkedin_service.seal_for_transit(
        {"email": str(payload.email), "password": payload.password}
    )

    await db.commit()
    celery_app.send_task(
        "linkedin.auth.connect_credentials",
        args=[str(account.id), sealed],
        queue="linkedin.action",
    )
    return _respond(account)


@router.post("/linkedin-accounts/{account_id}/challenge", response_model=ConnectResponse)
async def submit_challenge(
    account_id: uuid.UUID,
    payload: ChallengeSubmitRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConnectResponse:
    """Submit the verification code LinkedIn sent."""
    ctx.require_role(WorkspaceRole.ADMIN)
    account = await linkedin_service.get_account(db, ctx.workspace_id, account_id)

    if account.challenge_ciphertext is None:
        raise ConflictError("this account is not waiting for a verification code")

    account.status = LinkedInAccountStatus.CONNECTING
    sealed = linkedin_service.seal_for_transit({"code": payload.code.strip()})

    await db.commit()
    celery_app.send_task(
        "linkedin.auth.submit_challenge",
        args=[str(account.id), sealed],
        queue="linkedin.action",
    )
    return _respond(account)


@router.post("/linkedin-accounts/{account_id}/verify", response_model=ConnectResponse)
async def verify_session(
    account_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> ConnectResponse:
    """Probe the stored session now, rather than waiting for the Beat sweep."""
    account = await linkedin_service.get_account(db, ctx.workspace_id, account_id)
    if not account.is_connected:
        raise ConflictError("this account has no stored session to verify")

    await db.commit()
    celery_app.send_task("linkedin.auth.verify", args=[str(account.id)], queue="linkedin.sync")
    return _respond(account)


@router.patch("/linkedin-accounts/{account_id}", response_model=LinkedInAccountResponse)
async def update_account(
    account_id: uuid.UUID,
    payload: CapsUpdateRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LinkedInAccountResponse:
    """Update limits, working hours, test mode, timezone, or label."""
    ctx.require_role(WorkspaceRole.ADMIN)
    account = await linkedin_service.get_account(db, ctx.workspace_id, account_id)
    account = await linkedin_service.update_caps(db, ctx, account, payload)
    return linkedin_service.to_response(account)


@router.post("/linkedin-accounts/{account_id}/pause", response_model=LinkedInAccountResponse)
async def pause_account(
    account_id: uuid.UUID,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
    paused: bool = True,
) -> LinkedInAccountResponse:
    ctx.require_role(WorkspaceRole.ADMIN)
    account = await linkedin_service.get_account(db, ctx.workspace_id, account_id)
    account = await linkedin_service.set_paused(db, ctx, account, paused)
    return linkedin_service.to_response(account)


@router.post("/linkedin-accounts/{account_id}/disconnect", response_model=LinkedInAccountResponse)
async def disconnect_account(
    account_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> LinkedInAccountResponse:
    ctx.require_role(WorkspaceRole.ADMIN)
    account = await linkedin_service.get_account(db, ctx.workspace_id, account_id)
    account = await linkedin_service.disconnect(db, ctx, account)
    return linkedin_service.to_response(account)


@router.delete("/linkedin-accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_account(
    account_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> None:
    ctx.require_role(WorkspaceRole.ADMIN)
    account = await linkedin_service.get_account(db, ctx.workspace_id, account_id)
    await linkedin_service.delete_account(db, ctx, account)


# ── proxies ──────────────────────────────────────────────────────────────────


@router.get("/proxies", response_model=list[ProxyResponse])
async def list_proxies(
    ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[ProxyResponse]:
    stmt = (
        select(Proxy)
        .where((Proxy.workspace_id == ctx.workspace_id) | (Proxy.workspace_id.is_(None)))
        .order_by(Proxy.created_at)
    )
    proxies = (await db.execute(stmt)).scalars().all()
    return [
        ProxyResponse(
            id=p.id,
            label=p.label,
            provider=p.provider,
            public_url=p.public_url,
            country=p.country,
            city=p.city,
            status=p.status,
            last_exit_ip=p.last_exit_ip,
            last_checked_at=p.last_checked_at,
            assigned_account_id=p.assigned_account_id,
            created_at=p.created_at,
        )
        for p in proxies
    ]


@router.post("/proxies", response_model=ProxyResponse, status_code=status.HTTP_201_CREATED)
async def create_proxy(
    payload: ProxyCreateRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProxyResponse:
    """Register a proxy. Credentials are encrypted and never returned."""
    ctx.require_role(WorkspaceRole.ADMIN)

    if payload.password and not payload.username:
        raise ValidationFailedError("a proxy password needs a username")

    proxy = Proxy(
        workspace_id=ctx.workspace_id,
        label=payload.label or f"{payload.host}:{payload.port}",
        provider=payload.provider,
        scheme=payload.scheme,
        host=payload.host.strip(),
        port=payload.port,
        username_ciphertext=encrypt_str(payload.username) if payload.username else None,
        password_ciphertext=encrypt_str(payload.password) if payload.password else None,
        country=payload.country,
        city=payload.city,
        sticky_session_id=payload.sticky_session_id,
        # A new proxy is unbound by definition; stating it avoids a lazy load
        # when the response reports `assigned_account_id`.
        assigned_account=None,
    )
    db.add(proxy)
    await db.flush()

    await audit.record(
        db,
        "proxy.created",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="proxy",
        target_id=proxy.id,
        metadata={"host": proxy.host, "country": proxy.country, "provider": proxy.provider},
    )

    return ProxyResponse(
        id=proxy.id,
        label=proxy.label,
        provider=proxy.provider,
        public_url=proxy.public_url,
        country=proxy.country,
        city=proxy.city,
        status=proxy.status,
        last_exit_ip=proxy.last_exit_ip,
        last_checked_at=proxy.last_checked_at,
        assigned_account_id=proxy.assigned_account_id,
        created_at=proxy.created_at,
    )


@router.delete("/proxies/{proxy_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_proxy(
    proxy_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> None:
    ctx.require_role(WorkspaceRole.ADMIN)
    proxy = (
        await db.execute(
            select(Proxy).where(Proxy.id == proxy_id, Proxy.workspace_id == ctx.workspace_id)
        )
    ).scalar_one_or_none()
    if proxy is None:
        raise NotFoundError("proxy not found")
    if proxy.assigned_account_id is not None:
        raise ConflictError(
            "this proxy is bound to a LinkedIn account; disconnect that account first"
        )
    await db.delete(proxy)


# ── publishing authorization (official LinkedIn API) ─────────────────────────
#
# Entirely separate from the cookie/credential connect flows above. Those
# establish an automation session; this obtains a member-granted OAuth token
# with `w_member_social`, which is the only thing that may create a post.


@router.post(
    "/linkedin-accounts/{account_id}/publishing/authorize",
    response_model=PublishingAuthorizeResponse,
)
async def start_publishing_authorization(
    account_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> PublishingAuthorizeResponse:
    """Begins the LinkedIn consent flow for posting on this member's behalf."""
    ctx.require_role(WorkspaceRole.ADMIN)
    account = await linkedin_service.get_account(db, ctx.workspace_id, account_id)

    if not settings.linkedin_publishing_configured:
        raise ConflictError(
            "This deployment has no LinkedIn app configured, so posting permission "
            "cannot be requested. See docs/LINKEDIN_PUBLISHING_REQUIREMENTS.md.",
            details={"code": "not_configured"},
        )

    state = publishing.encode_state(ctx.workspace_id, account.id, ctx.user.id)
    await audit.record(
        db,
        "linkedin_account.publishing_authorization_started",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="linkedin_account",
        target_id=account.id,
    )
    return PublishingAuthorizeResponse(authorize_url=publishing.authorize_url(state))


@router.delete(
    "/linkedin-accounts/{account_id}/publishing", response_model=LinkedInAccountResponse
)
async def revoke_publishing_authorization(
    account_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> LinkedInAccountResponse:
    """Forgets the stored posting grant. Scheduled posts then fail loudly."""
    ctx.require_role(WorkspaceRole.ADMIN)
    account = await linkedin_service.get_account(db, ctx.workspace_id, account_id)
    publishing.clear_grant(account, reason="revoked by user")
    account.publishing_member_urn = ""
    account.publishing_authorized_at = None

    await audit.record(
        db,
        "linkedin_account.publishing_revoked",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="linkedin_account",
        target_id=account.id,
    )
    return linkedin_service.to_response(account)


oauth_router = APIRouter(prefix="/linkedin", tags=["linkedin"])


@oauth_router.get("/oauth/callback")
async def publishing_oauth_callback(
    db: Annotated[AsyncSession, Depends(get_db)],
    code: str = "",
    state: str = "",
    error: str = "",
    error_description: str = "",
) -> RedirectResponse:
    """LinkedIn's redirect target. Public by necessity, safe by signed state.

    There is no session on this request — the browser is arriving from
    linkedin.com — so the signed `state` is what proves which workspace, account
    and user the grant belongs to. It is short-lived and cannot be forged
    without the server's signing key.
    """
    web = settings.web_base_url.rstrip("/")

    def _back(status_key: str, message: str = "") -> RedirectResponse:
        query = urlencode({"publishing": status_key, **({"message": message} if message else {})})
        return RedirectResponse(f"{web}/accounts?{query}", status_code=303)

    if error:
        return _back("denied", error_description or error)
    if not code or not state:
        return _back("error", "LinkedIn did not return an authorization code")

    try:
        parsed = publishing.decode_state(state)
        granted = await anyio.to_thread.run_sync(publishing.exchange_code, code)
    except publishing.PublishingError as exc:
        return _back("error", exc.message)

    account = (
        await db.execute(
            select(LinkedInAccount).where(
                LinkedInAccount.id == parsed.account_id,
                LinkedInAccount.workspace_id == parsed.workspace_id,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        return _back("error", "that LinkedIn account no longer exists")

    if publishing.POST_SCOPE not in granted.scopes:
        # Granted something, but not the permission that matters. Storing it
        # would produce an account that looks authorized and cannot post.
        return _back(
            "missing_scope",
            "Posting permission was not granted. Reconnect and accept the "
            "“Create, modify, and delete posts” permission.",
        )

    publishing.store_grant(account, granted, actor_user_id=parsed.user_id)
    await audit.record(
        db,
        "linkedin_account.publishing_authorized",
        workspace_id=parsed.workspace_id,
        actor_user_id=parsed.user_id,
        target_type="linkedin_account",
        target_id=account.id,
        metadata={"scopes": granted.scopes},
    )
    return _back("connected")
