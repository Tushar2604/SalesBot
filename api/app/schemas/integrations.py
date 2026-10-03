"""Integration layer schemas: API keys, webhooks, deliveries."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WhoAmI(BaseModel):
    """What a key (or login) can see: handy for testing a new integration."""

    workspace_id: uuid.UUID
    workspace_name: str
    role: str
    via_api_key: bool
    api_key_name: str = ""


class EventType(BaseModel):
    type: str
    description: str


class ApiKeyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    prefix: str
    role: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    role: Literal["member", "admin"] = "member"


class ApiKeyCreated(BaseModel):
    key: ApiKeyResponse
    # The full key. Shown this once; only a hash is kept.
    secret: str


class WebhookResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    url: str
    description: str
    events: list[str]
    enabled: bool
    failure_streak: int
    disabled_reason: str
    last_success_at: datetime | None
    last_failure_at: datetime | None
    created_at: datetime


class WebhookCreate(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    description: str = Field(default="", max_length=200)
    events: list[str] = Field(min_length=1, max_length=50)


class WebhookUpdate(BaseModel):
    url: str | None = Field(default=None, min_length=8, max_length=2000)
    description: str | None = Field(default=None, max_length=200)
    events: list[str] | None = Field(default=None, min_length=1, max_length=50)
    enabled: bool | None = None


class WebhookCreated(BaseModel):
    webhook: WebhookResponse
    # The signing secret. Shown this once; rotate it to get a new one.
    secret: str


class DeliveryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    endpoint_id: uuid.UUID
    event_id: uuid.UUID
    event_type: str
    status: str
    attempts: int
    next_attempt_at: datetime | None
    delivered_at: datetime | None
    response_status: int | None
    response_body: str
    error: str
    duration_ms: int | None
    created_at: datetime
    payload: dict[str, Any]
