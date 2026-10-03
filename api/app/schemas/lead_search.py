"""AI lead finder schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LeadSearchStatus(BaseModel):
    # People-data providers with a key, in the order they are tried.
    providers: list[str]
    ready: bool
    # Whether an LLM can read requests; without one the message is searched as keywords.
    ai_available: bool
    daily_limit: int
    used_today: int


class LeadSearchChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    # Continue (refine) an earlier search; omitted = a new search.
    search_id: uuid.UUID | None = None


class FoundLead(BaseModel):
    public_id: str
    profile_url: str
    first_name: str = ""
    last_name: str = ""
    headline: str = ""
    title: str = ""
    company: str = ""
    location: str = ""
    avatar_url: str = ""
    provider: str = ""
    match_reasons: list[str] = []
    score: float = 0.0
    in_leads: bool = False


class ChatMessage(BaseModel):
    role: str
    text: str
    at: str = ""


class LeadSearchResponse(BaseModel):
    id: uuid.UUID
    title: str
    messages: list[ChatMessage]
    criteria: dict[str, Any]
    criteria_summary: str
    results: list[FoundLead]
    provider: str
    created_at: datetime
    updated_at: datetime


class LeadSearchChatResponse(BaseModel):
    search: LeadSearchResponse
    reply: str
    needs_clarification: bool
    notices: list[str]


class LeadSearchSummary(BaseModel):
    id: uuid.UUID
    title: str
    result_count: int
    updated_at: datetime


class ImportFoundRequest(BaseModel):
    public_ids: list[str] = Field(min_length=1, max_length=100)
    list_name: str = Field(default="", max_length=160)
