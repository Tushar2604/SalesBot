"""Integration layer: API keys (inbound REST) and webhooks (outbound events).

ApiKey              lets another system call this workspace's REST API
WebhookEndpoint     a URL that receives signed event notifications
WebhookDelivery     one event on its way to one endpoint (the outbox):
                    written in the same transaction as the change it
                    describes, delivered afterwards with retries
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
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, Timestamps, UUIDPrimaryKey
from app.models.tenancy import WorkspaceRole


class ApiKey(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        Index("ix_api_keys_workspace_id", "workspace_id"),
        Index("ux_api_keys_key_hash", "key_hash", unique=True),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    # Requests made with the key act as this person (for audit and role), and
    # stop working if they leave the workspace.
    created_by_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # The first characters, shown in the UI so a key can be recognised.
    prefix: Mapped[str] = mapped_column(String(24), nullable=False)
    # SHA-256 of the full key; the key itself is shown once and never stored.
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[WorkspaceRole] = mapped_column(
        Enum(WorkspaceRole, name="workspace_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=WorkspaceRole.MEMBER,
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookEndpoint(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "webhook_endpoints"
    __table_args__ = (Index("ix_webhook_endpoints_workspace_id", "workspace_id"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # Event types this endpoint receives; ["*"] = all of them.
    events: Mapped[list[str]] = mapped_column(ARRAY(String(60)), nullable=False, default=list)
    # Signing secret, encrypted at rest (shown to the user once).
    secret_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Consecutive failed attempts; a long enough streak switches it off.
    failure_streak: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    disabled_reason: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeliveryStatus(enum.StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class WebhookDelivery(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        Index("ix_webhook_deliveries_due", "status", "next_attempt_at"),
        Index("ix_webhook_deliveries_endpoint", "endpoint_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    endpoint_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("webhook_endpoints.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Same for every endpoint the event went to, so receivers can dedupe.
    event_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(
            DeliveryStatus,
            name="webhook_delivery_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=DeliveryStatus.PENDING,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sending_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    response_status: Mapped[int | None] = mapped_column(Integer)
    response_body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    duration_ms: Mapped[int | None] = mapped_column(Integer)
