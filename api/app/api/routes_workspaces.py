"""Workspace, membership, and invite management."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import CurrentUser, Workspace_, client_ip
from app.models.tenancy import WorkspaceRole
from app.schemas.auth import (
    InviteCreatedResponse,
    InviteCreateRequest,
    InviteResponse,
    MemberResponse,
    MemberRoleUpdateRequest,
    WorkspaceCreateRequest,
    WorkspaceResponse,
    WorkspaceUpdateRequest,
)
from app.services import audit, auth_service, workspace_service

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreateRequest,
    user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceResponse:
    workspace = await auth_service.create_workspace_for_user(db, user, payload.name)
    return WorkspaceResponse.model_validate(workspace)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(ctx: Workspace_) -> WorkspaceResponse:
    return WorkspaceResponse.model_validate(ctx.workspace)


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    payload: WorkspaceUpdateRequest,
    ctx: Workspace_,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceResponse:
    ctx.require_role(WorkspaceRole.ADMIN)

    if payload.name is not None:
        ctx.workspace.name = payload.name.strip()

    if (
        payload.outreach_paused is not None
        and payload.outreach_paused != ctx.workspace.outreach_paused
    ):
        ctx.workspace.outreach_paused = payload.outreach_paused
        # The kill switch is an operational event worth its own audit entry —
        # support needs to see who stopped outreach and when.
        await audit.record(
            db,
            "workspace.outreach_paused"
            if payload.outreach_paused
            else "workspace.outreach_resumed",
            workspace_id=ctx.workspace_id,
            actor_user_id=ctx.user.id,
            target_type="workspace",
            target_id=ctx.workspace_id,
            ip_address=client_ip(request),
        )

    return WorkspaceResponse.model_validate(ctx.workspace)


# ── members ───────────────────────────────────────────────────────────────────


@router.get("/{workspace_id}/members", response_model=list[MemberResponse])
async def list_members(
    ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[MemberResponse]:
    members = await workspace_service.list_members(db, ctx.workspace_id)
    return [MemberResponse.model_validate(m) for m in members]


@router.patch("/{workspace_id}/members/{member_id}", response_model=MemberResponse)
async def update_member_role(
    member_id: uuid.UUID,
    payload: MemberRoleUpdateRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MemberResponse:
    # Granting ownership is an owner-only act; admins may only manage members/admins.
    ctx.require_role(
        WorkspaceRole.OWNER if payload.role is WorkspaceRole.OWNER else WorkspaceRole.ADMIN
    )
    member = await workspace_service.update_member_role(
        db,
        workspace_id=ctx.workspace_id,
        member_id=member_id,
        new_role=payload.role,
        actor=ctx.user,
    )
    return MemberResponse.model_validate(member)


@router.delete("/{workspace_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    member_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> None:
    ctx.require_role(WorkspaceRole.ADMIN)
    await workspace_service.remove_member(
        db, workspace_id=ctx.workspace_id, member_id=member_id, actor=ctx.user
    )


# ── invites ───────────────────────────────────────────────────────────────────


@router.post(
    "/{workspace_id}/invites",
    response_model=InviteCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_invite(
    payload: InviteCreateRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> InviteCreatedResponse:
    ctx.require_role(WorkspaceRole.ADMIN)
    invite, raw_token = await workspace_service.create_invite(
        db,
        workspace=ctx.workspace,
        email=payload.email,
        role=payload.role,
        actor=ctx.user,
        actor_role=ctx.role,
    )
    return InviteCreatedResponse(
        **InviteResponse.model_validate(invite).model_dump(),
        invite_url=workspace_service.invite_url(raw_token),
    )


@router.get("/{workspace_id}/invites", response_model=list[InviteResponse])
async def list_invites(
    ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[InviteResponse]:
    ctx.require_role(WorkspaceRole.ADMIN)
    invites = await workspace_service.list_invites(db, ctx.workspace_id)
    return [InviteResponse.model_validate(i) for i in invites]


@router.delete("/{workspace_id}/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invite(
    invite_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> None:
    ctx.require_role(WorkspaceRole.ADMIN)
    await workspace_service.revoke_invite(
        db, workspace_id=ctx.workspace_id, invite_id=invite_id, actor=ctx.user
    )
