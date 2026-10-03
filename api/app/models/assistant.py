"""The AI assistant's knowledge base, and the named assistants campaigns pick.

Each knowledge item is something the assistant may share or rely on when it
replies — a job description, a pricing sheet, an FAQ answer. The assistant is
told to answer only from these items and to hand the conversation to a person
whenever they do not cover what was asked.

These are the SOPs of the UI. Each one can be attached to specific LinkedIn
accounts (none = every account) and to specific assistants (none = shared by
every assistant, the default one included).

An `AssistantProfile` is one named assistant — "HR recruiter", "Team
follow-up" — with its own voice, instructions, hand-off rules and questions
to ask. A campaign picks one (`campaign.settings["assistant_id"]`), so leads
from an HR campaign are answered by the HR assistant from the HR SOPs.
Threads with no campaign, or whose campaign picks none, use the workspace's
default assistant (`workspace.settings["assistant"]`).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class KnowledgeItem(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "knowledge_items"
    __table_args__ = (Index("ix_knowledge_items_workspace_id", "workspace_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Off = kept, but not shown to the assistant.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # The LinkedIn accounts this applies to; empty = every account. No FK (an
    # array can't carry one): an id left over from a removed account matches
    # nothing, which is harmless.
    linkedin_account_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )
    # The assistants this applies to; empty = every assistant, the default one
    # included. Same no-FK reasoning as above.
    assistant_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(PGUUID(as_uuid=True)), nullable=False, default=list, server_default="{}"
    )


class AssistantProfile(UUIDPrimaryKey, Timestamps, Base):
    """One named assistant a campaign can pick. Pace and daily caps stay
    workspace-wide; this decides who it speaks as and what it does."""

    __tablename__ = "assistant_profiles"
    __table_args__ = (Index("ix_assistant_profiles_workspace_id", "workspace_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # "inherit" follows the workspace mode; "draft" never sends by itself;
    # "off" stays silent in this assistant's threads. Never louder than the
    # workspace: with the workspace off, every assistant is off.
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="inherit")
    persona: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    handoff_topics: Mapped[str] = mapped_column(Text, nullable=False, default="")
    collect_fields: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
