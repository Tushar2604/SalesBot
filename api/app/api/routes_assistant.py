"""AI assistant endpoints: settings, knowledge base, and a dry-run "try it".

The assistant itself runs in workers (`app/worker/tasks/assistant.py`); these
routes only configure it. "Try it" calls Claude directly but never touches
LinkedIn, so it is safe to use while shaping the persona and knowledge base.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import assistant as ai
from app.db import get_db
from app.deps import Workspace_
from app.models.assistant import AssistantProfile, KnowledgeItem
from app.models.tenancy import WorkspaceRole
from app.schemas.assistant import (
    AssistantProfileCreate,
    AssistantProfileResponse,
    AssistantProfileUpdate,
    AssistantSettings,
    AssistantSettingsUpdate,
    KnowledgeItemCreate,
    KnowledgeItemResponse,
    KnowledgeItemUpdate,
    SharedFactResponse,
    TryRequest,
    TryResponse,
)
from app.services import assistant_service

router = APIRouter(prefix="/workspaces/{workspace_id}/assistant", tags=["assistant"])


def _available() -> bool:
    return bool(ai.available_providers())


@router.get("/settings", response_model=AssistantSettings)
async def get_settings(
    ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> AssistantSettings:
    return AssistantSettings(
        **await assistant_service.get_settings(db, ctx.workspace_id), ai_available=_available()
    )


@router.put("/settings", response_model=AssistantSettings)
async def put_settings(
    payload: AssistantSettingsUpdate, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> AssistantSettings:
    ctx.require_role(WorkspaceRole.ADMIN)
    patch = payload.model_dump(exclude_none=True, exclude={"acknowledge_risk"})
    return AssistantSettings(
        **await assistant_service.update_settings(
            db, ctx, patch, acknowledge_risk=payload.acknowledge_risk
        ),
        ai_available=_available(),
    )


@router.get("/knowledge", response_model=list[KnowledgeItemResponse])
async def list_knowledge(
    ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[KnowledgeItem]:
    return await assistant_service.list_knowledge(db, ctx.workspace_id)


@router.post(
    "/knowledge", response_model=KnowledgeItemResponse, status_code=status.HTTP_201_CREATED
)
async def create_knowledge(
    payload: KnowledgeItemCreate, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> KnowledgeItem:
    ctx.require_role(WorkspaceRole.MEMBER)
    return await assistant_service.create_knowledge(
        db,
        ctx,
        payload.title,
        payload.content,
        payload.enabled,
        payload.linkedin_account_ids,
        payload.assistant_ids,
    )


@router.patch("/knowledge/{item_id}", response_model=KnowledgeItemResponse)
async def update_knowledge(
    item_id: uuid.UUID,
    payload: KnowledgeItemUpdate,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> KnowledgeItem:
    ctx.require_role(WorkspaceRole.MEMBER)
    return await assistant_service.update_knowledge(
        db, ctx, item_id, payload.model_dump(exclude_none=True)
    )


@router.delete("/knowledge/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge(
    item_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> None:
    ctx.require_role(WorkspaceRole.MEMBER)
    await assistant_service.delete_knowledge(db, ctx, item_id)


# ── named assistants ─────────────────────────────────────────────────────────


@router.get("/profiles", response_model=list[AssistantProfileResponse])
async def list_profiles(
    ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[AssistantProfile]:
    return await assistant_service.list_profiles(db, ctx.workspace_id)


@router.post(
    "/profiles", response_model=AssistantProfileResponse, status_code=status.HTTP_201_CREATED
)
async def create_profile(
    payload: AssistantProfileCreate, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> AssistantProfile:
    ctx.require_role(WorkspaceRole.MEMBER)
    return await assistant_service.create_profile(db, ctx, payload.model_dump())


@router.patch("/profiles/{profile_id}", response_model=AssistantProfileResponse)
async def update_profile(
    profile_id: uuid.UUID,
    payload: AssistantProfileUpdate,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AssistantProfile:
    ctx.require_role(WorkspaceRole.MEMBER)
    return await assistant_service.update_profile(
        db, ctx, profile_id, payload.model_dump(exclude_none=True)
    )


@router.delete("/profiles/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_profile(
    profile_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> None:
    ctx.require_role(WorkspaceRole.MEMBER)
    await assistant_service.delete_profile(db, ctx, profile_id)


@router.post("/try", response_model=TryResponse)
async def try_it(
    payload: TryRequest, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> TryResponse:
    """What the assistant would do with this conversation. Sends nothing."""
    ctx.require_role(WorkspaceRole.MEMBER)
    profile = (
        await assistant_service.get_profile(db, ctx.workspace_id, payload.assistant_id)
        if payload.assistant_id
        else None
    )
    cfg = assistant_service.effective_settings(
        await assistant_service.get_settings(db, ctx.workspace_id), profile
    )
    items = (
        await db.execute(
            assistant_service.knowledge_query(
                ctx.workspace_id, payload.linkedin_account_id, payload.assistant_id
            )
        )
    ).scalars()
    knowledge = [ai.KnowledgeDoc(i.title, i.content) for i in items]
    decision = await asyncio.to_thread(
        ai.decide,
        ai.AssistantConfig(
            cfg["persona"], cfg["instructions"], cfg["handoff_topics"], tuple(cfg["collect_fields"])
        ),
        knowledge,
        [ai.Turn(t.from_me, t.text) for t in payload.turns],
        payload.prospect_name,
    )
    if decision is None:
        return TryResponse(action="unavailable")
    return TryResponse(
        action=decision.action,
        reply=decision.reply,
        handoff_reason=decision.handoff_reason,
        shared_facts=[
            SharedFactResponse(field=f.field, value=f.value) for f in decision.shared_facts
        ],
    )
