"""Lead and campaign schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.campaigns import (
    CampaignStatus,
    ConditionFailAction,
    EnrollmentState,
    StepCondition,
    StepType,
)
from app.models.leads import BlocklistKind, ImportStatus, LeadSource

# ── leads ────────────────────────────────────────────────────────────────────


class LeadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    public_id: str
    profile_url: str
    first_name: str
    last_name: str
    full_name: str
    headline: str
    company: str
    title: str
    location: str
    email: str
    source: LeadSource
    custom_fields: dict[str, Any]
    list_id: uuid.UUID | None
    created_at: datetime


class LeadPage(BaseModel):
    items: list[LeadResponse]
    total: int
    limit: int
    offset: int


class LeadListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    source: LeadSource
    import_status: ImportStatus
    import_detail: str
    total_rows: int
    imported_count: int
    skipped_count: int
    created_at: datetime


class RowProblem(BaseModel):
    row_number: int
    reason: str
    public_id: str = ""


class ImportReportResponse(BaseModel):
    """Every row is accounted for, so an import is never a silent partial."""

    list_id: uuid.UUID
    list_name: str
    total_rows: int
    imported: int
    updated: int
    skipped: int
    problems: list[RowProblem]


class ImportUrlsRequest(BaseModel):
    """Leads pasted directly as LinkedIn profile links or bare handles."""

    urls: str = Field(min_length=1, max_length=50_000)
    list_name: str = ""


class CsvPreviewResponse(BaseModel):
    """Headers and the mapping we guessed, for confirmation before importing."""

    headers: list[str]
    guessed_mapping: dict[str, str]
    sample_rows: list[dict[str, str]]
    mappable_fields: list[str]


class BlocklistEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    kind: BlocklistKind
    value: str
    note: str
    created_at: datetime


class BlocklistCreateRequest(BaseModel):
    kind: BlocklistKind
    value: str = Field(min_length=1, max_length=320)
    note: str = Field(default="", max_length=400)


# ── campaigns ────────────────────────────────────────────────────────────────


class StepRequest(BaseModel):
    step_type: StepType
    delay_hours: int = Field(default=0, ge=0, le=24 * 60)
    only_if: StepCondition = StepCondition.ALWAYS
    on_condition_fail: ConditionFailAction = ConditionFailAction.SKIP
    template: str = Field(default="", max_length=8000)
    # When the step runs. "smart" = a human-like time inside working hours (the
    # default); "asap" = as soon as the account's limits allow; "delay" = exactly
    # `delay_minutes` after the previous step; "at" = at `send_at`.
    timing: Literal["smart", "asap", "delay", "at"] = "smart"
    delay_minutes: int | None = Field(default=None, ge=0, le=60 * 24 * 60)
    send_at: datetime | None = None

    @field_validator("template")
    @classmethod
    def _trim(cls, value: str) -> str:
        return value.strip()


class StepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_index: int
    step_type: StepType
    delay_hours: int
    only_if: StepCondition
    on_condition_fail: ConditionFailAction
    template: str
    timing: Literal["smart", "asap", "delay", "at"] = "smart"
    delay_minutes: int | None = None
    send_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def _lift_timing(cls, data: Any) -> Any:
        """Timing lives in the step's JSON `config`; surface it as real fields."""
        config = getattr(data, "config", None)
        if config is None:
            return data
        return {
            "id": data.id,
            "order_index": data.order_index,
            "step_type": data.step_type,
            "delay_hours": data.delay_hours,
            "only_if": data.only_if,
            "on_condition_fail": data.on_condition_fail,
            "template": data.template,
            "timing": config.get("timing", "smart"),
            "delay_minutes": config.get("delay_minutes"),
            "send_at": config.get("send_at"),
        }


class CampaignCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    linkedin_account_id: uuid.UUID
    steps: list[StepRequest] = Field(min_length=1, max_length=20)
    stop_on_reply: bool = True


class CampaignUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    stop_on_reply: bool | None = None


class CampaignStatsResponse(BaseModel):
    enrolled: int
    pending: int
    running: int
    completed: int
    replied: int
    stopped: int
    skipped: int
    failed: int
    invites_sent: int
    accepted: int
    messages_sent: int
    views: int
    tasks_pending: int
    tasks_failed: int
    acceptance_rate: float | None
    reply_rate: float | None


class CampaignResponse(BaseModel):
    id: uuid.UUID
    name: str
    status: CampaignStatus
    stop_on_reply: bool
    linkedin_account_id: uuid.UUID
    linkedin_account_label: str
    steps: list[StepResponse]
    stats: CampaignStatsResponse
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    # Why the campaign cannot be launched right now, if it cannot.
    launch_blockers: list[str] = []


class EnrollRequest(BaseModel):
    list_id: uuid.UUID | None = None
    lead_ids: list[uuid.UUID] = Field(default_factory=list, max_length=5000)


class EnrollReportResponse(BaseModel):
    enrolled: int
    skipped_duplicate: int
    skipped_blocked: int
    skipped_already_enrolled: int
    skipped_no_profile: int
    total_skipped: int


class StatusChangeRequest(BaseModel):
    status: CampaignStatus


class EnrollmentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    lead_id: uuid.UUID
    lead_name: str
    lead_public_id: str
    lead_company: str
    state: EnrollmentState
    current_step_index: int
    variant: str
    next_run_at: datetime | None
    invite_sent_at: datetime | None
    accepted_at: datetime | None
    replied_at: datetime | None
    last_error: str
    stopped_reason: str


class EnrollmentPage(BaseModel):
    items: list[EnrollmentResponse]
    total: int


class TemplatePreviewRequest(BaseModel):
    template: str = Field(max_length=8000)


class TemplatePreviewResponse(BaseModel):
    rendered: str
    variables: list[str]
    variables_without_fallback: list[str]
    length: int
    exceeds_invite_limit: bool


class ActionTaskResponse(BaseModel):
    """A queued or completed action — the operator's view of what the engine did."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    action_type: StepType
    status: str
    scheduled_at: datetime
    dispatched_at: datetime | None
    finished_at: datetime | None
    attempts: int
    error_class: str
    error_detail: str
    lead_public_id: str = ""


class QuotaStatusResponse(BaseModel):
    """What the safety engine will and will not allow right now."""

    linkedin_account_id: uuid.UUID
    label: str
    status: str
    within_working_hours: bool
    working_hours_detail: str
    next_allowed_at: datetime | None
    blocked_reason: str
    invites_used_today: int
    invites_limit_today: int
    invites_used_this_week: int
    invites_limit_this_week: int
    invite_limit_reason: str
    messages_used_today: int
    messages_limit_today: int
    views_used_today: int
    views_limit_today: int


# ── tracking ─────────────────────────────────────────────────────────────────


class TrackingStageCount(BaseModel):
    stage: str
    label: str
    count: int


class TrackingSummaryResponse(BaseModel):
    campaign_id: uuid.UUID
    campaign_name: str
    campaign_status: str
    total: int
    # One bucket per lead (they add up to `total`), in funnel order.
    stages: list[TrackingStageCount]
    # Cumulative: how many ever reached each step.
    viewed: int
    invited: int
    connected: int
    messaged: int
    replied: int
    acceptance_rate: float | None
    still_waiting: int
    not_accepted: int
    expired: int
    answered: int
    oldest_pending_days: int | None
    avg_days_to_accept: float | None
    next_check_at: datetime | None
    tracking_window_days: int


class TrackingLeadResponse(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    lead_name: str
    lead_public_id: str
    lead_company: str
    lead_title: str
    stage: str
    stage_label: str
    reason: str
    viewed_at: datetime | None
    invite_sent_at: datetime | None
    days_waiting: int | None
    accepted_at: datetime | None
    resolved_at: datetime | None
    last_checked_at: datetime | None
    next_check_at: datetime | None
    check_count: int
    replied_at: datetime | None
    last_event_type: str
    last_event_detail: str
    last_event_at: datetime | None


class TrackingLeadPage(BaseModel):
    items: list[TrackingLeadResponse]
    total: int


class LeadEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    event_type: str
    detail: str
    occurred_at: datetime
    meta: dict[str, Any]
