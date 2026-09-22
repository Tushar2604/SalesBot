"""AI assistant settings and knowledge base.

Settings live in `workspace.settings["assistant"]` (no table needed); the
knowledge base is the `knowledge_items` table. `resolve_settings` is the one
place defaults and bounds are applied, so the worker and the API always agree
on what a stored value means.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.deps import WorkspaceContext
from app.models.assistant import KnowledgeItem
from app.models.tenancy import Workspace
from app.services import audit

DEFAULTS: dict[str, Any] = {
    # "off" | "draft" (suggest, a person sends) | "auto" (send by itself)
    "mode": "off",
    "persona": "",
    "instructions": "",
    "handoff_topics": "",
    "reply_delay_min_minutes": 2,
    "reply_delay_max_minutes": 8,
    "max_replies_per_thread_per_day": 3,
    "max_replies_per_account_per_day": 20,
    "working_hours_only": True,
}

_BOUNDS: dict[str, tuple[int, int]] = {
    "reply_delay_min_minutes": (1, 240),
    "reply_delay_max_minutes": (1, 480),
    "max_replies_per_thread_per_day": (1, 20),
    "max_replies_per_account_per_day": (1, 100),
}


def resolve_settings(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Stored settings with defaults filled and numbers clamped to safe ranges."""
    merged = {**DEFAULTS, **(raw or {})}
    if merged["mode"] not in ("off", "draft", "auto"):
        merged["mode"] = "off"
    for key, (low, high) in _BOUNDS.items():
        try:
            merged[key] = max(low, min(high, int(merged[key])))
        except (TypeError, ValueError):
            merged[key] = DEFAULTS[key]
    merged["reply_delay_max_minutes"] = max(
        merged["reply_delay_max_minutes"], merged["reply_delay_min_minutes"]
    )
    merged["working_hours_only"] = bool(merged["working_hours_only"])
    for key in ("persona", "instructions", "handoff_topics"):
        merged[key] = str(merged[key] or "")[:4000]
    return {key: merged[key] for key in DEFAULTS}


async def get_settings(db: AsyncSession, workspace_id: uuid.UUID) -> dict[str, Any]:
    workspace = await db.get(Workspace, workspace_id)
    return resolve_settings((workspace.settings or {}).get("assistant") if workspace else None)


async def update_settings(
    db: AsyncSession, ctx: WorkspaceContext, patch: dict[str, Any]
) -> dict[str, Any]:
    workspace = await db.get(Workspace, ctx.workspace_id)
    if workspace is None:
        raise NotFoundError("workspace not found")
    current = (workspace.settings or {}).get("assistant") or {}
    updated = resolve_settings({**current, **patch})
    # Reassign rather than mutate so SQLAlchemy sees the JSONB change.
    workspace.settings = {**(workspace.settings or {}), "assistant": updated}
    await audit.record(
        db,
        "assistant.settings_updated",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="workspace",
        target_id=ctx.workspace_id,
        metadata={"mode": updated["mode"], "changed": sorted(patch)},
    )
    await db.commit()
    return updated


async def list_knowledge(db: AsyncSession, workspace_id: uuid.UUID) -> list[KnowledgeItem]:
    rows = await db.execute(
        select(KnowledgeItem)
        .where(KnowledgeItem.workspace_id == workspace_id)
        .order_by(KnowledgeItem.created_at.desc())
    )
    return list(rows.scalars())


async def _get_item(db: AsyncSession, workspace_id: uuid.UUID, item_id: uuid.UUID) -> KnowledgeItem:
    item = await db.get(KnowledgeItem, item_id)
    if item is None or item.workspace_id != workspace_id:
        raise NotFoundError("knowledge item not found")
    return item


async def create_knowledge(
    db: AsyncSession, ctx: WorkspaceContext, title: str, content: str, enabled: bool
) -> KnowledgeItem:
    item = KnowledgeItem(
        workspace_id=ctx.workspace_id, title=title, content=content, enabled=enabled
    )
    db.add(item)
    await db.flush()
    await audit.record(
        db,
        "assistant.knowledge_created",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="knowledge_item",
        target_id=item.id,
        metadata={"title": title},
    )
    await db.commit()
    await db.refresh(item)
    return item


async def update_knowledge(
    db: AsyncSession, ctx: WorkspaceContext, item_id: uuid.UUID, patch: dict[str, Any]
) -> KnowledgeItem:
    item = await _get_item(db, ctx.workspace_id, item_id)
    for key in ("title", "content", "enabled"):
        if key in patch and patch[key] is not None:
            setattr(item, key, patch[key])
    await db.commit()
    await db.refresh(item)
    return item


async def delete_knowledge(db: AsyncSession, ctx: WorkspaceContext, item_id: uuid.UUID) -> None:
    item = await _get_item(db, ctx.workspace_id, item_id)
    await db.delete(item)
    await audit.record(
        db,
        "assistant.knowledge_deleted",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="knowledge_item",
        target_id=item_id,
        metadata={"title": item.title},
    )
    await db.commit()
