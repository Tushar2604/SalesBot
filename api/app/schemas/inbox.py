"""Inbox schemas: conversations and messages."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.inbox import ConversationLabel, LabelSource, MessageDirection

# ── conversations ────────────────────────────────────────────────────────────


class ConversationResponse(BaseModel):
    """Flattened, not nested: matches how `EnrollmentResponse` joins a lead in."""

    id: uuid.UUID
    linkedin_account_id: uuid.UUID
    linkedin_account_label: str
    lead_id: uuid.UUID | None
    lead_name: str
    lead_public_id: str
    campaign_lead_id: uuid.UUID | None
    participant_urn: str
    participant_name: str
    last_message_at: datetime | None
    last_message_text: str
    last_message_from_me: bool
    unread: bool
    label: ConversationLabel
    label_source: LabelSource
    snoozed_until: datetime | None
    created_at: datetime
    bot_paused: bool = False
    bot_pause_reason: str = ""
    bot_draft: str = ""
    bot_draft_at: datetime | None = None
    bot_extracted: dict[str, str] = {}


class ConversationPage(BaseModel):
    items: list[ConversationResponse]
    total: int
    limit: int
    offset: int


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    direction: MessageDirection
    body: str
    sent_at: datetime
    ai_label: ConversationLabel | None
    author: str = ""


class SendReplyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def _trim(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reply text cannot be empty")
        return value


class LabelRequest(BaseModel):
    label: ConversationLabel


class SnoozeRequest(BaseModel):
    until: datetime | None = None
