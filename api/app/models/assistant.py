"""The AI assistant's knowledge base.

Each item is something the assistant may share or rely on when it replies —
a job description, a pricing sheet, an FAQ answer. The assistant is told to
answer only from these items and to hand the conversation to a person
whenever they do not cover what was asked.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, Text
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
