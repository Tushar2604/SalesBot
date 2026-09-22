"""Dashboard analytics: real per-day counts, no placeholder rows."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import Workspace_
from app.schemas.analytics import AnalyticsOverviewResponse, DailySeriesResponse
from app.services import analytics_service

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["analytics"])


@router.get("/analytics/overview", response_model=AnalyticsOverviewResponse)
async def get_overview(
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> AnalyticsOverviewResponse:
    result = await analytics_service.overview(db, ctx.workspace_id, days=days)
    return AnalyticsOverviewResponse(
        days=result.days,
        series=[DailySeriesResponse(key=s.key, label=s.label, counts=s.counts) for s in result.series],
        total_campaigns=result.total_campaigns,
        running_campaigns=result.running_campaigns,
        prospects_reached=result.prospects_reached,
        total_connected=result.total_connected,
        total_replies=result.total_replies,
    )
