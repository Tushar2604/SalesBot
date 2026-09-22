"""Campaigns, sequence steps, enrollments, action tasks, and the quota ledger.

The central object is `ActionTask`: **every** outbound action is a durable row
with a unique idempotency key. That is what makes the system safe under
redelivery — `acks_late` means a killed worker's task comes back, and the
constraint, not luck, is what stops a prospect being invited twice.

Sequences are an ordered list of steps, each optionally gated by a condition
(`only_if`). A gate that fails either skips the step or stops the enrollment.
This covers the real branching people use — "message only if they accepted",
"follow up only if they haven't replied" — without a general DAG, which would
be far more surface area for the same outcomes.
"""

from __future__ import annotations

import enum
import hashlib
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class CampaignStatus(enum.StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"


class StepType(enum.StrEnum):
    """What a sequence step does.

    `VIEW_PROFILE` is not filler: it is a cheap, visible, low-risk action that
    both warms the prospect and keeps the account's write/read ratio plausible.
    """

    VIEW_PROFILE = "view_profile"
    INVITE = "invite"
    MESSAGE = "message"
    WITHDRAW_INVITE = "withdraw_invite"
    WAIT = "wait"


class StepCondition(enum.StrEnum):
    """Gate evaluated immediately before a step runs."""

    ALWAYS = "always"
    IF_ACCEPTED = "if_accepted"
    IF_NOT_ACCEPTED = "if_not_accepted"
    IF_REPLIED = "if_replied"
    IF_NOT_REPLIED = "if_not_replied"


class ConditionFailAction(enum.StrEnum):
    SKIP = "skip"  # move on to the next step
    STOP = "stop"  # end the enrollment here


class EnrollmentState(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    REPLIED = "replied"  # terminal: they answered, hands off
    COMPLETED = "completed"
    STOPPED = "stopped"  # terminal: a condition or an operator ended it
    FAILED = "failed"
    SKIPPED = "skipped"  # never started: duplicate, blocklisted, invalid

    @property
    def is_terminal(self) -> bool:
        return self in {
            EnrollmentState.REPLIED,
            EnrollmentState.COMPLETED,
            EnrollmentState.STOPPED,
            EnrollmentState.FAILED,
            EnrollmentState.SKIPPED,
        }


class ConnectionState(enum.StrEnum):
    """Where a lead's connection request stands on LinkedIn.

    LinkedIn never tells the sender that a request was declined, so the only
    honest states are what the profile itself shows: still pending, connected,
    or neither (`NOT_ACCEPTED` — declined, withdrawn or lapsed, indistinguishable
    from outside). `EXPIRED` is ours: we stopped watching after the tracking window.
    """

    NONE = "none"  # no invite sent yet
    PENDING = "pending"
    CONNECTED = "connected"
    NOT_ACCEPTED = "not_accepted"
    EXPIRED = "expired"


class TaskStatus(enum.StrEnum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class Campaign(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        Index("ix_campaigns_workspace_id", "workspace_id"),
        Index("ix_campaigns_status", "status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    # A campaign sends from exactly one account, so its pacing and quota are
    # unambiguous. Multi-sender rotation is a later feature built on top.
    linkedin_account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("linkedin_accounts.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[CampaignStatus] = mapped_column(
        Enum(
            CampaignStatus,
            name="campaign_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=CampaignStatus.DRAFT,
    )
    # When true, an inbound reply ends that lead's sequence immediately. This is
    # the behaviour that stops the "awkward double-message" everyone complains
    # about, so it defaults on.
    stop_on_reply: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    steps: Mapped[list[CampaignStep]] = relationship(
        back_populates="campaign",
        cascade="all, delete-orphan",
        order_by="CampaignStep.order_index",
        lazy="selectin",
    )


class CampaignStep(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "campaign_steps"
    __table_args__ = (
        UniqueConstraint("campaign_id", "order_index", name="uq_campaign_steps_campaign_order"),
        Index("ix_campaign_steps_campaign_id", "campaign_id"),
    )

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[StepType] = mapped_column(
        Enum(StepType, name="step_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    # Delay measured from the completion of the previous step, not from
    # enrollment: "2 days after the invite", which is how users think.
    delay_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    only_if: Mapped[StepCondition] = mapped_column(
        Enum(StepCondition, name="step_condition", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=StepCondition.ALWAYS,
    )
    on_condition_fail: Mapped[ConditionFailAction] = mapped_column(
        Enum(
            ConditionFailAction,
            name="condition_fail_action",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ConditionFailAction.SKIP,
    )
    # Message body / invite note, with {{variables}} and {spintax|variants}.
    template: Mapped[str] = mapped_column(Text, nullable=False, default="")
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    campaign: Mapped[Campaign] = relationship(back_populates="steps")


class CampaignLead(UUIDPrimaryKey, Timestamps, Base):
    """One lead's journey through one campaign. The state machine."""

    __tablename__ = "campaign_leads"
    __table_args__ = (
        # A lead is enrolled in a campaign once.
        UniqueConstraint("campaign_id", "lead_id", name="uq_campaign_leads_campaign_lead"),
        Index("ix_campaign_leads_campaign_id", "campaign_id"),
        # The enrollment tick's query: due work, cheapest possible index hit.
        Index("ix_campaign_leads_due", "state", "next_run_at"),
        Index("ix_campaign_leads_account", "linkedin_account_id"),
        # The acceptance tracker's query: pending invites whose check is due.
        Index("ix_campaign_leads_check", "connection_state", "next_check_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("leads.id", ondelete="CASCADE"), nullable=False
    )
    linkedin_account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("linkedin_accounts.id", ondelete="CASCADE"), nullable=False
    )

    state: Mapped[EnrollmentState] = mapped_column(
        Enum(
            EnrollmentState,
            name="enrollment_state",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=EnrollmentState.PENDING,
    )
    current_step_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # When the enrollment tick should next look at this row.
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Milestones that conditions read.
    invite_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    replied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Connection tracking. `connection_state` is the latest observation; the full
    # history lives in `campaign_lead_events`.
    connection_state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=ConnectionState.NONE.value, server_default="none"
    )
    viewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # When the invite stopped being pending (accepted, not accepted, or expired).
    connection_resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # A/B variant, assigned deterministically from the enrollment id.
    variant: Mapped[str] = mapped_column(String(8), nullable=False, default="A")
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    stopped_reason: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    lead: Mapped[Any] = relationship("Lead", lazy="selectin")


class EventType(enum.StrEnum):
    ENROLLED = "enrolled"
    PROFILE_VIEWED = "profile_viewed"
    INVITE_SENT = "invite_sent"
    INVITE_STILL_PENDING = "invite_still_pending"
    INVITE_ACCEPTED = "invite_accepted"
    INVITE_NOT_ACCEPTED = "invite_not_accepted"
    INVITE_EXPIRED = "invite_expired"
    MESSAGE_SENT = "message_sent"
    REPLIED = "replied"
    ACTION_FAILED = "action_failed"
    ACTION_SKIPPED = "action_skipped"
    SEQUENCE_ENDED = "sequence_ended"


class CampaignLeadEvent(UUIDPrimaryKey, Base):
    """Append-only history of everything that happened to one lead in a campaign.

    Never updated or deleted by the app: it is the record the tracking page reads,
    so "what happened to this person and when" survives whatever the enrollment's
    current state later becomes.
    """

    __tablename__ = "campaign_lead_events"
    __table_args__ = (
        Index("ix_campaign_lead_events_lead", "campaign_lead_id", "occurred_at"),
        Index("ix_campaign_lead_events_campaign", "campaign_id", "event_type"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    campaign_lead_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("campaign_leads.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    detail: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class ActionTask(UUIDPrimaryKey, Base):
    """One scheduled outbound action. Durable and idempotent.

    `idempotency_key` is the safety property: derived from the enrollment, the
    step, and the attempt, so a broker redelivery or a racing dispatcher cannot
    produce two invites to the same person.
    """

    __tablename__ = "action_tasks"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_action_tasks_idempotency_key"),
        # The dispatcher's hot query: next due task for one account.
        Index("ix_action_tasks_claim", "linkedin_account_id", "status", "scheduled_at"),
        Index("ix_action_tasks_enrollment", "campaign_lead_id"),
        Index("ix_action_tasks_workspace_created", "workspace_id", "created_at"),
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now()
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    linkedin_account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("linkedin_accounts.id", ondelete="CASCADE"), nullable=False
    )
    campaign_lead_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("campaign_leads.id", ondelete="CASCADE")
    )
    step_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("campaign_steps.id", ondelete="SET NULL")
    )

    action_type: Mapped[StepType] = mapped_column(
        Enum(StepType, name="step_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=TaskStatus.PENDING,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)

    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    error_class: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    error_detail: Mapped[str] = mapped_column(Text, nullable=False, default="")

    @staticmethod
    def build_idempotency_key(
        campaign_lead_id: uuid.UUID | None,
        step_id: uuid.UUID | None,
        attempt_bucket: int = 0,
    ) -> str:
        raw = f"{campaign_lead_id}:{step_id}:{attempt_bucket}"
        return hashlib.sha256(raw.encode()).hexdigest()


class DailyQuotaLedger(Base):
    """Source of truth for "how many did we already do today".

    A table rather than a Redis counter: quotas must survive a cache flush, and
    the trailing-7-day invite window has to be queryable historically.
    """

    __tablename__ = "daily_quota_ledger"

    linkedin_account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("linkedin_accounts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    # The account's *local* date, not UTC: a day means a day where the user is.
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    action_type: Mapped[StepType] = mapped_column(
        Enum(StepType, name="step_type", values_callable=lambda e: [m.value for m in e]),
        primary_key=True,
    )
    used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
