"""Analytics schemas: the Dashboard's "Your Analytics" panel."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class DailySeriesResponse(BaseModel):
    key: str
    label: str
    counts: list[int]


class AnalyticsOverviewResponse(BaseModel):
    days: list[date]
    series: list[DailySeriesResponse]
    total_campaigns: int
    running_campaigns: int
    prospects_reached: int
    total_connected: int
    total_replies: int
