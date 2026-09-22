"""AI assistant schemas: settings, knowledge base, try-it."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AssistantSettings(BaseModel):
    mode: Literal["off", "draft", "auto"]
    persona: str
    instructions: str
    handoff_topics: str
    reply_delay_min_minutes: int
    reply_delay_max_minutes: int
    max_replies_per_thread_per_day: int
    max_replies_per_account_per_day: int
    working_hours_only: bool
    # Read-only: whether the server has a Claude API key at all.
    ai_available: bool = True


class AssistantSettingsUpdate(BaseModel):
    mode: Literal["off", "draft", "auto"] | None = None
    persona: str | None = Field(default=None, max_length=4000)
    instructions: str | None = Field(default=None, max_length=4000)
    handoff_topics: str | None = Field(default=None, max_length=4000)
    reply_delay_min_minutes: int | None = Field(default=None, ge=1, le=240)
    reply_delay_max_minutes: int | None = Field(default=None, ge=1, le=480)
    max_replies_per_thread_per_day: int | None = Field(default=None, ge=1, le=20)
    max_replies_per_account_per_day: int | None = Field(default=None, ge=1, le=100)
    working_hours_only: bool | None = None


class KnowledgeItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    content: str
    enabled: bool
    created_at: datetime
    updated_at: datetime


class KnowledgeItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=50_000)
    enabled: bool = True


class KnowledgeItemUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1, max_length=50_000)
    enabled: bool | None = None


class TryTurn(BaseModel):
    from_me: bool
    text: str = Field(min_length=1, max_length=2000)


class TryRequest(BaseModel):
    """A pretend conversation, to see what the assistant would do. Nothing is sent."""

    turns: list[TryTurn] = Field(min_length=1, max_length=30)
    prospect_name: str = Field(default="Sample Prospect", max_length=120)


class SharedFactResponse(BaseModel):
    field: str
    value: str


class TryResponse(BaseModel):
    action: Literal["reply", "handoff", "no_reply", "unavailable"]
    reply: str = ""
    handoff_reason: str = ""
    shared_facts: list[SharedFactResponse] = []


class BotControlRequest(BaseModel):
    paused: bool


class SendDraftRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
