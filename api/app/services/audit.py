"""Audit trail writer.

Every state-changing action that touches outreach, credentials, membership, or
billing must land here. When a customer's LinkedIn account gets restricted, this
table is how you reconstruct exactly what the system did on their behalf.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models.tenancy import AuditEvent


def _build(
    action: str,
    *,
    workspace_id: uuid.UUID | None,
    actor_user_id: uuid.UUID | None,
    target_type: str,
    target_id: str | uuid.UUID,
    metadata: dict[str, Any] | None,
    ip_address: str,
    note: str,
) -> AuditEvent:
    return AuditEvent(
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        metadata_=metadata or {},
        ip_address=ip_address,
        note=note,
    )


async def record(
    db: AsyncSession,
    action: str,
    *,
    workspace_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    target_type: str = "",
    target_id: str | uuid.UUID = "",
    metadata: dict[str, Any] | None = None,
    ip_address: str = "",
    note: str = "",
) -> None:
    db.add(
        _build(
            action,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            target_type=target_type,
            target_id=target_id,
            metadata=metadata,
            ip_address=ip_address,
            note=note,
        )
    )


def record_sync(
    db: Session,
    action: str,
    *,
    workspace_id: uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    target_type: str = "",
    target_id: str | uuid.UUID = "",
    metadata: dict[str, Any] | None = None,
    note: str = "",
) -> None:
    """Worker-side variant — used by the dispatcher and action executors."""
    db.add(
        _build(
            action,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            target_type=target_type,
            target_id=target_id,
            metadata=metadata,
            ip_address="",
            note=note,
        )
    )
