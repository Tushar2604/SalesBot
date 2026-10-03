"""AI lead finder: chat to find prospects, then add them to a lead list.

Searches go to licensed people-data providers, never through a LinkedIn
account (see app/leadsearch/__init__.py for why).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import Workspace_
from app.leadsearch.criteria import SearchCriteria
from app.models.lead_search import LeadSearch
from app.models.tenancy import WorkspaceRole
from app.schemas.lead_search import (
    ChatMessage,
    FoundLead,
    ImportFoundRequest,
    LeadSearchChatRequest,
    LeadSearchChatResponse,
    LeadSearchResponse,
    LeadSearchStatus,
    LeadSearchSummary,
)
from app.schemas.outreach import ImportReportResponse, RowProblem
from app.services import lead_search_service

router = APIRouter(prefix="/workspaces/{workspace_id}/lead-search", tags=["lead-search"])


def _to_response(search: LeadSearch) -> LeadSearchResponse:
    criteria = search.criteria or {}
    return LeadSearchResponse(
        id=search.id,
        title=search.title,
        messages=[ChatMessage(**m) for m in search.messages or []],
        criteria=criteria,
        criteria_summary=SearchCriteria(**criteria).describe() if criteria else "",
        results=[FoundLead(**r) for r in search.results or []],
        provider=search.provider,
        created_at=search.created_at,
        updated_at=search.updated_at,
    )


@router.get("/status", response_model=LeadSearchStatus)
async def get_status(
    ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> LeadSearchStatus:
    return LeadSearchStatus(
        **lead_search_service.status(),
        used_today=await lead_search_service.searches_today(db, ctx.workspace_id),
    )


@router.post("/chat", response_model=LeadSearchChatResponse)
async def chat(
    payload: LeadSearchChatRequest, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> LeadSearchChatResponse:
    ctx.require_role(WorkspaceRole.MEMBER)
    outcome = await lead_search_service.chat(db, ctx, payload.message, payload.search_id)
    await db.refresh(outcome.search)
    return LeadSearchChatResponse(
        search=_to_response(outcome.search),
        reply=outcome.reply,
        needs_clarification=outcome.needs_clarification,
        notices=outcome.notices,
    )


@router.get("/searches", response_model=list[LeadSearchSummary])
async def list_searches(
    ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[LeadSearchSummary]:
    return [
        LeadSearchSummary(
            id=s.id,
            title=s.title or "Untitled search",
            result_count=len(s.results or []),
            updated_at=s.updated_at,
        )
        for s in await lead_search_service.list_searches(db, ctx.workspace_id)
    ]


@router.get("/searches/{search_id}", response_model=LeadSearchResponse)
async def get_search(
    search_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> LeadSearchResponse:
    return _to_response(await lead_search_service.get_search(db, ctx.workspace_id, search_id))


@router.post(
    "/searches/{search_id}/import",
    response_model=ImportReportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def import_found(
    search_id: uuid.UUID,
    payload: ImportFoundRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ImportReportResponse:
    """Adds the chosen people to a new lead list, ready for a campaign."""
    ctx.require_role(WorkspaceRole.MEMBER)
    report = await lead_search_service.import_results(
        db, ctx, search_id, payload.public_ids, payload.list_name
    )
    return ImportReportResponse(
        list_id=report.list_id,
        list_name=report.list_name,
        total_rows=report.total_rows,
        imported=report.imported,
        updated=report.updated,
        skipped=report.skipped,
        problems=[
            RowProblem(row_number=p.row_number, reason=p.reason, public_id=p.public_id)
            for p in report.problems
        ],
    )
