"""LinkedIn conversations and messages: the unified inbox.

A `Conversation` is one LinkedIn thread on one account. It is a materialized
view of what `poll_replies` already reads live to stop a sequence — this
module exists so that same data can also be shown to a human, labeled,
snoozed, and replied to. It does not change how a sequence gets stopped;
`CampaignLead.replied_at`/`state` (see `app.models.campaigns`) remains the
single source of truth for that.

`label`/`label_source` let an AI classification and a human override coexist:
the AI sets `label_source=AI` freely, but once a person sets a label
(`label_source=MANUAL`) a later classification never overwrites it.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class ConversationLabel(enum.StrEnum):
    NONE = "none"
    INTERESTED = "interested"
    NOT_INTERESTED = "not_interested"
    OUT_OF_OFFICE = "out_of_office"
    QUESTION = "question"
    OTHER = "other"


class LabelSource(enum.StrEnum):
    MANUAL = "manual"
    AI = "ai"


class MessageDirection(enum.StrEnum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class Conversation(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        # One row per thread per account — re-polling updates it in place.
        UniqueConstraint(
            "linkedin_account_id", "conversation_urn", name="uq_conversations_account_urn"
        ),
        Index("ix_conversations_workspace_id", "workspace_id"),
        Index("ix_conversations_account_id", "linkedin_account_id"),
        Index("ix_conversations_lead_id", "lead_id"),
        # The inbox list query: newest activity first, within a workspace.
        Index("ix_conversations_inbox_list", "workspace_id", "last_message_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    linkedin_account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("linkedin_accounts.id", ondelete="CASCADE"), nullable=False
    )
    lead_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("leads.id", ondelete="SET NULL")
    )
    campaign_lead_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("campaign_leads.id", ondelete="SET NULL")
    )

    conversation_urn: Mapped[str] = mapped_column(String(200), nullable=False)
    participant_urn: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    participant_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_message_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    last_message_from_me: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    unread: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    label: Mapped[ConversationLabel] = mapped_column(
        Enum(
            ConversationLabel,
            name="conversation_label",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=ConversationLabel.NONE,
    )
    # Defaults to AI, not MANUAL: nobody has looked at a brand-new thread yet,
    # so classification must be free to set the first label. Only a human
    # explicitly setting a label flips this to MANUAL, after which AI no
    # longer overwrites it.
    label_source: Mapped[LabelSource] = mapped_column(
        Enum(LabelSource, name="label_source", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=LabelSource.AI,
    )
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── AI assistant state ──────────────────────────────────────────────────
    # A paused bot never replies in this thread until a person resumes it.
    # Set when a human replies (here or on LinkedIn itself), when the bot hands
    # off, or by hand from the inbox.
    bot_paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    bot_pause_reason: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Refreshed while someone is typing in this thread in the inbox. The bot
    # waits until it lapses, so it never talks over a person mid-reply.
    human_active_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Draft mode: the reply the bot proposes, waiting for a person to send it.
    bot_draft: Mapped[str] = mapped_column(Text, nullable=False, default="")
    bot_draft_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Facts the prospect shared (email, phone, availability, ...), accumulated.
    bot_extracted: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class MessageAuthor(enum.StrEnum):
    """Who produced an outbound message. Empty for inbound, and for outbound
    rows first seen on LinkedIn that nothing in this app sent."""

    BOT = "bot"
    HUMAN = "human"
    CAMPAIGN = "campaign"


class Message(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_workspace_id", "workspace_id"),
        Index("ix_messages_conversation_id", "conversation_id", "sent_at"),
        # A real LinkedIn event id is unique per conversation; an empty one
        # (synthesized rows, or events LinkedIn doesn't id) must not collide,
        # so the uniqueness only applies when there is a real id to protect.
        Index(
            "uq_messages_conversation_event",
            "conversation_id",
            "remote_event_urn",
            unique=True,
            postgresql_where=text("remote_event_urn <> ''"),
        ),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )

    remote_event_urn: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    direction: Mapped[MessageDirection] = mapped_column(
        Enum(
            MessageDirection,
            name="message_direction",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    author: Mapped[str] = mapped_column(String(16), nullable=False, default="")

    ai_label: Mapped[ConversationLabel | None] = mapped_column(
        Enum(
            ConversationLabel,
            name="conversation_label",
            values_callable=lambda e: [m.value for m in e],
        )
    )
    ai_classified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
