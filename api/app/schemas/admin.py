"""Platform admin panel: every LinkedIn account, who runs it, and its risk."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.linkedin import LinkedInAccountStatus


class AdminMember(BaseModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    role: str


class AdminAccount(BaseModel):
    id: uuid.UUID
    label: str
    full_name: str
    public_id: str
    profile_url: str
    status: LinkedInAccountStatus
    status_detail: str
    health_score: int
    test_mode: bool
    proxy: str
    last_action_at: datetime | None
    connected_at: datetime

    workspace_id: uuid.UUID
    workspace_name: str
    connected_by_email: str
    connected_by_name: str
    members: list[AdminMember]

    warning_count: int
    warning_limit: int
    risk_level: str
    last_warning: str
    last_warning_at: datetime | None
    active_campaigns: int


class AdminRiskEvent(BaseModel):
    id: uuid.UUID
    source: str
    kind: str
    strikes: int
    detail: str
    actor_email: str
    created_at: datetime
    cleared_at: datetime | None
    counts: bool


class AdminActionRequest(BaseModel):
    reason: str = Field(default="", max_length=300)
