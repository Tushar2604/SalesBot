"""Remote-browser LinkedIn login: mint a session, then drive it over a WebSocket.

Two REST endpoints persist intent and mint a short-lived, single-use ticket —
mirroring how `routes_linkedin.py`'s cookie/credentials connect endpoints
commit before enqueueing background work. The WebSocket route is where the
actual browser session lives; it authenticates via the ticket (a query
parameter) rather than the normal bearer-token dependency, because a native
browser WebSocket cannot send an Authorization header.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Annotated

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.core.security import TokenError, decode_ws_ticket, encode_ws_ticket
from app.db import AsyncSessionLocal, get_db
from app.deps import Workspace_
from app.linkedin.remote_browser import LaunchFailed, RemoteBrowserError, manager
from app.linkedin.remote_browser.protocol import input_message_adapter
from app.models.linkedin import LinkedInAccount
from app.models.tenancy import WorkspaceMember, WorkspaceRole
from app.schemas.linkedin import (
    LinkedInAccountResponse,
    RemoteBrowserConnectRequest,
    RemoteSessionResponse,
)
from app.services import linkedin_service

log = get_logger(__name__)

# A WebSocket close reason is a control frame, capped at 123 bytes total by
# the protocol (RFC 6455) — not 123 *characters*. Playwright's own error
# messages can run to several KB and often contain multi-byte box-drawing
# characters, so a naive `str(exc)[:120]` can still overflow the limit and
# crash the close() call itself. Truncate by encoded bytes instead.
_MAX_CLOSE_REASON_BYTES = 100


def _safe_close_reason(text: str) -> str:
    return text.encode("utf-8")[:_MAX_CLOSE_REASON_BYTES].decode("utf-8", errors="ignore")

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["linkedin"])
ws_router = APIRouter(prefix="/linkedin", tags=["linkedin"])

_TICKET_TTL = timedelta(seconds=30)


@router.post(
    "/linkedin-accounts/connect/remote-browser",
    response_model=LinkedInAccountResponse,
    status_code=status.HTTP_201_CREATED,
)
async def connect_remote_browser(
    payload: RemoteBrowserConnectRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> LinkedInAccountResponse:
    """Creates the account row a remote-browser session will sign in as.

    No background work is enqueued here — unlike the cookie/credentials
    endpoints, the actual sign-in happens live, over the WebSocket the caller
    opens next with a ticket from `/remote-session`.
    """
    ctx.require_role(WorkspaceRole.ADMIN)
    account = await linkedin_service.create_account(
        db,
        ctx,
        label=payload.label,
        login_email="",
        timezone=payload.timezone,
        proxy_id=payload.proxy_id,
    )
    return linkedin_service.to_response(account)


@router.post(
    "/linkedin-accounts/{account_id}/remote-session",
    response_model=RemoteSessionResponse,
)
async def start_remote_session(
    account_id: uuid.UUID,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> RemoteSessionResponse:
    ctx.require_role(WorkspaceRole.ADMIN)
    # Raises NotFoundError (404) if the account doesn't exist or belongs to
    # another workspace — that check is the point of this call.
    await linkedin_service.get_account(db, ctx.workspace_id, account_id)

    ticket, _jti, _expires_at = encode_ws_ticket(
        ctx.user.id, ctx.workspace_id, account_id, _TICKET_TTL
    )
    scheme = "wss" if settings.web_base_url.startswith("https") else "ws"
    host = settings.api_base_url.split("://", 1)[-1]
    ws_url = f"{scheme}://{host}/api/v1/linkedin/remote-session/ws?ticket={ticket}"
    return RemoteSessionResponse(
        ticket=ticket, ws_url=ws_url, expires_in=int(_TICKET_TTL.total_seconds())
    )


async def _consume_ticket_once(jti: str, ttl_seconds: int) -> bool:
    client: aioredis.Redis = aioredis.from_url(  # type: ignore[no-untyped-call]
        settings.redis_url, decode_responses=True
    )
    try:
        return bool(await client.set(f"ws:ticket:{jti}", "1", nx=True, ex=max(ttl_seconds, 1)))
    finally:
        await client.aclose()


async def _verify_membership(db: AsyncSession, user_id: uuid.UUID, workspace_id: uuid.UUID) -> None:
    stmt = (
        select(WorkspaceMember)
        .options(selectinload(WorkspaceMember.workspace))
        .where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.user_id == user_id)
    )
    membership = (await db.execute(stmt)).scalar_one_or_none()
    if membership is None or membership.workspace.deleted_at is not None:
        raise NotFoundError("workspace not found")


@ws_router.websocket("/remote-session/ws")
async def remote_session_ws(websocket: WebSocket, ticket: Annotated[str, Query()]) -> None:
    try:
        claims = decode_ws_ticket(ticket)
    except TokenError:
        await websocket.close(code=4000, reason="invalid or expired ticket")
        return

    user_id = uuid.UUID(claims["sub"])
    workspace_id = uuid.UUID(claims["ws"])
    account_id = uuid.UUID(claims["acct"])
    jti = claims["jti"]
    remaining = max(int(claims["exp"]) - int(claims["iat"]), 1)

    if not await _consume_ticket_once(jti, remaining):
        await websocket.close(code=4000, reason="ticket already used")
        return

    async with AsyncSessionLocal() as db:
        try:
            await _verify_membership(db, user_id, workspace_id)
            account = (
                await db.execute(
                    select(LinkedInAccount).where(
                        LinkedInAccount.id == account_id,
                        LinkedInAccount.workspace_id == workspace_id,
                    )
                )
            ).scalar_one_or_none()
        except NotFoundError:
            account = None

    if account is None:
        await websocket.close(code=4000, reason="account not found")
        return

    await websocket.accept()

    try:
        session = await manager.start(account_id, workspace_id)
    except RemoteBrowserError as exc:
        await websocket.close(code=exc.close_code, reason=_safe_close_reason(str(exc)))
        return
    except Exception as exc:
        log.error("remote_browser.ws_start_failed", account_id=str(account_id), error=str(exc))
        await websocket.close(code=LaunchFailed.close_code, reason="could not start the browser")
        return

    async def _reader() -> None:
        while True:
            raw = await websocket.receive_text()
            try:
                message = input_message_adapter.validate_json(raw)
            except Exception as exc:  # malformed input frame — skip it, keep the session alive
                log.debug("remote_browser.bad_input_frame", error=str(exc))
                continue
            await session.dispatch_input(message)

    async def _writer() -> None:
        while True:
            frame_task = asyncio.ensure_future(session.frame_queue.get())
            status_task = asyncio.ensure_future(session.status_queue.get())
            done, pending = await asyncio.wait(
                {frame_task, status_task}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            if frame_task in done:
                await websocket.send_bytes(frame_task.result())
            if status_task in done:
                await websocket.send_json(status_task.result().model_dump())

    reader_task = asyncio.ensure_future(_reader())
    writer_task = asyncio.ensure_future(_writer())
    try:
        await asyncio.wait({reader_task, writer_task}, return_when=asyncio.FIRST_COMPLETED)
    except WebSocketDisconnect:
        pass
    finally:
        reader_task.cancel()
        writer_task.cancel()
        await manager.stop(account_id, reason="ws_closed")
