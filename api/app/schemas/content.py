"""Content Studio schemas.

As elsewhere, note what never appears in a response: the LinkedIn access token,
its refresh token, the OAuth client secret, or a raw storage key. The client sees
a capability verdict and presigned preview URLs, never a credential.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.content import MediaKind, PostStatus, PostVisibility


def _validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"“{value}” is not a known IANA timezone") from exc
    return value


# ── media ────────────────────────────────────────────────────────────────────


class MediaAssetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: MediaKind
    filename: str
    content_type: str
    size_bytes: int
    width: int
    height: int
    # Short-lived presigned URL. The bucket itself stays private.
    url: str
    created_at: datetime


class PostMediaInput(BaseModel):
    media_asset_id: uuid.UUID
    alt_text: str = Field(default="", max_length=400)


class PostMediaResponse(BaseModel):
    id: uuid.UUID
    position: int
    alt_text: str
    asset: MediaAssetResponse


# ── posts ────────────────────────────────────────────────────────────────────


class PostCreateRequest(BaseModel):
    linkedin_account_id: uuid.UUID
    content: str = Field(default="", max_length=20000)
    visibility: PostVisibility = PostVisibility.PUBLIC
    media: list[PostMediaInput] = Field(default_factory=list)


class PostUpdateRequest(BaseModel):
    """Every field optional: this is also the autosave payload."""

    linkedin_account_id: uuid.UUID | None = None
    content: str | None = Field(default=None, max_length=20000)
    visibility: PostVisibility | None = None
    media: list[PostMediaInput] | None = None


class ScheduleRequest(BaseModel):
    """A local wall-clock time plus its zone, converted to UTC server-side.

    The client does not send a UTC instant it computed itself: browser zone data
    and the user's chosen zone are routinely different, and the user's choice is
    the one that must win.
    """

    scheduled_date: date
    # 24-hour local time.
    scheduled_time: str = Field(pattern=r"^\d{2}:\d{2}$")
    timezone: str = Field(max_length=64)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        return _validate_timezone(value)


class PublishingCapabilityResponse(BaseModel):
    code: str
    available: bool
    message: str
    # "" | "configure" | "authorize"
    remedy: str


class PostAccountSummary(BaseModel):
    """Enough of the account to render a post card and the preview header."""

    id: uuid.UUID
    label: str
    full_name: str
    headline: str
    avatar_url: str
    profile_url: str
    can_publish: bool
    capability: PublishingCapabilityResponse


class PostAnalyticsResponse(BaseModel):
    """Real upstream numbers, or an explicit statement that there are none.

    There is no zero-filled default here on purpose: a row of zeros would be
    indistinguishable from a post nobody engaged with.
    """

    available: bool
    message: str
    impressions: int | None = None
    likes: int | None = None
    comments: int | None = None
    reposts: int | None = None
    clicks: int | None = None
    engagement_rate: float | None = None
    updated_at: datetime | None = None


class PostResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    created_by_id: uuid.UUID | None
    created_by_name: str
    account: PostAccountSummary

    content: str
    visibility: PostVisibility
    status: PostStatus
    is_editable: bool

    character_count: int
    word_count: int
    hashtags: list[str]

    scheduled_at: datetime | None
    scheduled_timezone: str
    queue_position: int | None
    published_at: datetime | None
    linkedin_post_id: str
    linkedin_url: str

    failure_reason: str
    error_code: str
    request_id: str
    failed_at: datetime | None
    attempts: int

    submitted_for_approval_at: datetime | None
    approved_at: datetime | None
    approved_by_id: uuid.UUID | None
    review_note: str

    media: list[PostMediaResponse]
    analytics: PostAnalyticsResponse

    created_at: datetime
    updated_at: datetime


class PostPage(BaseModel):
    items: list[PostResponse]
    total: int
    limit: int
    offset: int
    counts: dict[str, int]


class CalendarEntry(BaseModel):
    """One dot on the calendar. Trimmed to what a cell can render."""

    id: uuid.UUID
    status: PostStatus
    excerpt: str
    at: datetime
    local_date: date
    local_time: str
    timezone: str
    account_label: str
    has_media: bool


class CalendarResponse(BaseModel):
    start: date
    end: date
    timezone: str
    entries: list[CalendarEntry]


# ── templates ────────────────────────────────────────────────────────────────


class TemplateCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    content: str = Field(default="", max_length=20000)
    media_asset_ids: list[uuid.UUID] = Field(default_factory=list)


class TemplateUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    content: str | None = Field(default=None, max_length=20000)
    media_asset_ids: list[uuid.UUID] | None = None


class TemplateResponse(BaseModel):
    id: uuid.UUID
    name: str
    content: str
    media: list[MediaAssetResponse]
    created_by_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


# ── queue ────────────────────────────────────────────────────────────────────


class QueueSlot(BaseModel):
    # 0 = Monday, matching `datetime.weekday()`.
    weekday: int = Field(ge=0, le=6)
    time: str = Field(pattern=r"^\d{2}:\d{2}$")


class QueueUpdateRequest(BaseModel):
    paused: bool | None = None
    timezone: str | None = Field(default=None, max_length=64)
    slots: list[QueueSlot] | None = None

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str | None) -> str | None:
        return None if value is None else _validate_timezone(value)


class QueueResponse(BaseModel):
    paused: bool
    timezone: str
    slots: list[QueueSlot]
    items: list[PostResponse]
    next_slot_at: datetime | None


class QueueAddRequest(BaseModel):
    """Appends to the queue; the next free slot decides the time."""

    linkedin_account_id: uuid.UUID | None = None


class QueueMoveRequest(BaseModel):
    direction: str = Field(pattern="^(up|down)$")


# ── AI ───────────────────────────────────────────────────────────────────────


class AiImproveRequest(BaseModel):
    content: str = Field(min_length=1, max_length=20000)
    action: str = Field(
        description=(
            "rewrite | shorter | longer | professional | conversational | hook | "
            "cta | hashtags | grammar | variations | repurpose"
        )
    )


class AiGenerateRequest(BaseModel):
    topic: str = Field(min_length=1, max_length=500)
    audience: str = Field(default="", max_length=300)
    tone: str = Field(default="professional", max_length=60)
    goal: str = Field(default="engagement", max_length=60)


class AiResponse(BaseModel):
    """Suggestions only. Nothing here is ever published without a human action."""

    variants: list[str]
    note: str = ""


# ── approval / workspace settings ────────────────────────────────────────────


class ApprovalSettingsRequest(BaseModel):
    approval_required: bool


class ApprovalSettingsResponse(BaseModel):
    approval_required: bool
    can_approve: bool


class ReviewRequest(BaseModel):
    note: str = Field(default="", max_length=2000)


class MediaLimitsResponse(BaseModel):
    limits: dict[str, Any]
