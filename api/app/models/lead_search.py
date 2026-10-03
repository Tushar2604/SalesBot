"""AI lead finder sessions.

One row per chat: the messages, the criteria the last message resolved to,
and the people it returned. Importing reads the people from here, so what
lands in `leads` is what the provider said, never what the browser sent back.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class LeadSearch(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "lead_searches"
    __table_args__ = (Index("ix_lead_searches_workspace_created", "workspace_id", "created_at"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # [{"role": "user" | "assistant", "text": str, "at": iso}]
    messages: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    criteria: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # The latest results, as Candidate.to_dict() rows.
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    # Provider calls made in this chat, counted against the daily limit.
    runs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
