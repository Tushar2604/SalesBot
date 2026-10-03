"""AI assistant settings, named assistants, and the knowledge base.

The default assistant's settings live in `workspace.settings["assistant"]`
(no table needed): its mode is the workspace's master switch, and its pace and
daily caps apply to every assistant. Named assistants (`assistant_profiles`)
each carry their own voice, instructions, hand-off rules and questions; a
campaign picks one, and `effective_settings` lays it over the workspace ones.
The knowledge base is the `knowledge_items` table. `resolve_settings` is the
one place defaults and bounds are applied, so the worker and the API always
agree on what a stored value means.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationFailedError
from app.deps import WorkspaceContext
from app.linkedin import risk
from app.models.assistant import AssistantProfile, KnowledgeItem
from app.models.campaigns import Campaign
from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus
from app.models.tenancy import Workspace
from app.services import audit

DEFAULTS: dict[str, Any] = {
    # "off" | "draft" (suggest, a person sends) | "auto" (send by itself)
    "mode": "off",
    "persona": "",
    "instructions": "",
    "handoff_topics": "",
    # A fresh random wait per reply in this range, never an instant answer.
    "reply_delay_min_minutes": 3,
    "reply_delay_max_minutes": 9,
    "max_replies_per_thread_per_day": 3,
    "max_replies_per_account_per_day": 20,
    "working_hours_only": True,
    "collect_fields": [],
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
    fields = merged["collect_fields"] if isinstance(merged["collect_fields"], list) else []
    merged["collect_fields"] = [
        str(f).strip()[:80] for f in fields if str(f).strip()
    ][:15]
    for key in ("persona", "instructions", "handoff_topics"):
        merged[key] = str(merged[key] or "")[:4000]
    return {key: merged[key] for key in DEFAULTS}


async def get_settings(db: AsyncSession, workspace_id: uuid.UUID) -> dict[str, Any]:
    workspace = await db.get(Workspace, workspace_id)
    return resolve_settings((workspace.settings or {}).get("assistant") if workspace else None)


async def update_settings(
    db: AsyncSession,
    ctx: WorkspaceContext,
    patch: dict[str, Any],
    *,
    acknowledge_risk: bool = False,
) -> dict[str, Any]:
    workspace = await db.get(Workspace, ctx.workspace_id)
    if workspace is None:
        raise NotFoundError("workspace not found")
    current = (workspace.settings or {}).get("assistant") or {}
    updated = resolve_settings({**current, **patch})

    # Automatic replying is workspace-wide, so an accepted risk is a warning on
    # every account it will speak for.
    already = {r.key for r in risk.assistant_risks(resolve_settings(current))}
    risks = [r for r in risk.assistant_risks(updated) if r.key not in already]
    risk.require_acknowledgement(risks, acknowledge_risk)
    if risks:
        accounts = list((await db.execute(
            select(LinkedInAccount).where(
                LinkedInAccount.workspace_id == ctx.workspace_id,
                LinkedInAccount.status != LinkedInAccountStatus.DISABLED,
            )
        )).scalars())
        await risk.record_overrides(db, accounts, risks, ctx.user.id)
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


def knowledge_query(
    workspace_id: uuid.UUID,
    account_id: uuid.UUID | None = None,
    assistant_id: uuid.UUID | None = None,
) -> Select[Any]:
    """The enabled items the assistant reads when replying from `account_id`
    as `assistant_id`: those attached to that account or to every account,
    and to that assistant or to every assistant. The default assistant
    (`assistant_id` None) reads only the ones shared by every assistant, so
    the HR assistant's SOPs never reach a team follow-up.

    A plain statement, so the async API and the sync worker share it."""
    for_account = func.cardinality(KnowledgeItem.linkedin_account_ids) == 0
    if account_id is not None:
        for_account = or_(for_account, KnowledgeItem.linkedin_account_ids.contains([account_id]))
    for_assistant = func.cardinality(KnowledgeItem.assistant_ids) == 0
    if assistant_id is not None:
        for_assistant = or_(for_assistant, KnowledgeItem.assistant_ids.contains([assistant_id]))
    return (
        select(KnowledgeItem)
        .where(
            KnowledgeItem.workspace_id == workspace_id,
            KnowledgeItem.enabled.is_(True),
            for_account,
            for_assistant,
        )
        .order_by(KnowledgeItem.created_at)
    )


# ── named assistants ─────────────────────────────────────────────────────────

PROFILE_MODES = ("inherit", "draft", "off")


def effective_settings(
    workspace_cfg: dict[str, Any], profile: AssistantProfile | None
) -> dict[str, Any]:
    """The settings one thread runs under: the workspace's, with its campaign's
    assistant laid over them. Pace and daily caps always stay the workspace's.

    An assistant can only be quieter than the workspace, never louder: "draft"
    turns auto into draft, "off" silences it, and a workspace that is off
    keeps every assistant off. So picking an assistant never needs the risk
    acknowledgement that turning on auto mode does."""
    cfg = dict(workspace_cfg)
    cfg["assistant_id"] = None
    cfg["assistant_name"] = "Default assistant"
    if profile is None:
        return cfg
    cfg["assistant_id"] = profile.id
    cfg["assistant_name"] = profile.name
    for key in ("persona", "instructions", "handoff_topics"):
        cfg[key] = str(getattr(profile, key) or "")[:4000]
    fields = profile.collect_fields if isinstance(profile.collect_fields, list) else []
    cfg["collect_fields"] = [str(f).strip()[:80] for f in fields if str(f).strip()][:15]
    if profile.mode == "off":
        cfg["mode"] = "off"
    elif profile.mode == "draft" and cfg["mode"] == "auto":
        cfg["mode"] = "draft"
    return cfg


def campaign_assistant_id(campaign: Campaign | None) -> uuid.UUID | None:
    """The assistant a campaign picked, if any (stored in its settings JSON)."""
    raw = (campaign.settings or {}).get("assistant_id") if campaign is not None else None
    try:
        return uuid.UUID(str(raw)) if raw else None
    except ValueError:
        return None


async def list_profiles(db: AsyncSession, workspace_id: uuid.UUID) -> list[AssistantProfile]:
    rows = await db.execute(
        select(AssistantProfile)
        .where(AssistantProfile.workspace_id == workspace_id)
        .order_by(AssistantProfile.created_at)
    )
    return list(rows.scalars())


async def get_profile(
    db: AsyncSession, workspace_id: uuid.UUID, profile_id: uuid.UUID
) -> AssistantProfile:
    profile = await db.get(AssistantProfile, profile_id)
    if profile is None or profile.workspace_id != workspace_id:
        raise NotFoundError("assistant not found")
    return profile


def _clean_profile_patch(patch: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    if "name" in patch:
        name = str(patch["name"] or "").strip()[:120]
        if not name:
            raise ValidationFailedError("Give the assistant a name")
        clean["name"] = name
    if "mode" in patch:
        if patch["mode"] not in PROFILE_MODES:
            raise ValidationFailedError("Unknown assistant mode")
        clean["mode"] = patch["mode"]
    for key in ("persona", "instructions", "handoff_topics"):
        if key in patch:
            clean[key] = str(patch[key] or "")[:4000]
    if "collect_fields" in patch:
        fields = patch["collect_fields"] or []
        clean["collect_fields"] = list(
            dict.fromkeys(str(f).strip()[:80] for f in fields if str(f).strip())
        )[:15]
    return clean


async def create_profile(
    db: AsyncSession, ctx: WorkspaceContext, values: dict[str, Any]
) -> AssistantProfile:
    clean = _clean_profile_patch({"name": "", "mode": "inherit", **values})
    profile = AssistantProfile(workspace_id=ctx.workspace_id, **clean)
    db.add(profile)
    await db.flush()
    await audit.record(
        db,
        "assistant.profile_created",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="assistant_profile",
        target_id=profile.id,
        metadata={"name": profile.name},
    )
    await db.commit()
    await db.refresh(profile)
    return profile


async def update_profile(
    db: AsyncSession, ctx: WorkspaceContext, profile_id: uuid.UUID, patch: dict[str, Any]
) -> AssistantProfile:
    profile = await get_profile(db, ctx.workspace_id, profile_id)
    clean = _clean_profile_patch(patch)
    for key, value in clean.items():
        setattr(profile, key, value)
    await audit.record(
        db,
        "assistant.profile_updated",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="assistant_profile",
        target_id=profile.id,
        metadata={"changed": sorted(clean)},
    )
    await db.commit()
    await db.refresh(profile)
    return profile


async def delete_profile(db: AsyncSession, ctx: WorkspaceContext, profile_id: uuid.UUID) -> None:
    """Campaigns that used it fall back to the default assistant. Its SOPs
    stay attached to their other assistants; one that was only attached to
    this assistant is switched off, because with no assistants left it would
    otherwise become shared by every assistant (an HR SOP leaking into every
    thread)."""
    profile = await get_profile(db, ctx.workspace_id, profile_id)
    items = (
        await db.execute(
            select(KnowledgeItem).where(
                KnowledgeItem.workspace_id == ctx.workspace_id,
                KnowledgeItem.assistant_ids.contains([profile.id]),
            )
        )
    ).scalars()
    for item in items:
        remaining = [a for a in item.assistant_ids if a != profile.id]
        if not remaining:
            item.enabled = False
        item.assistant_ids = remaining
    campaigns = (
        await db.execute(select(Campaign).where(Campaign.workspace_id == ctx.workspace_id))
    ).scalars()
    for campaign in campaigns:
        if campaign_assistant_id(campaign) == profile.id:
            campaign.settings = {
                k: v for k, v in (campaign.settings or {}).items() if k != "assistant_id"
            }
    await db.delete(profile)
    await audit.record(
        db,
        "assistant.profile_deleted",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="assistant_profile",
        target_id=profile_id,
        metadata={"name": profile.name},
    )
    await db.commit()


async def _check_assistants(
    db: AsyncSession, workspace_id: uuid.UUID, assistant_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """The ids deduplicated, once each is known to be this workspace's assistant."""
    wanted = list(dict.fromkeys(assistant_ids))
    if not wanted:
        return []
    found = set(
        (
            await db.execute(
                select(AssistantProfile.id).where(
                    AssistantProfile.workspace_id == workspace_id,
                    AssistantProfile.id.in_(wanted),
                )
            )
        ).scalars()
    )
    if len(found) != len(wanted):
        raise ValidationFailedError("One of the selected assistants is not in this workspace")
    return wanted


async def _check_accounts(
    db: AsyncSession, workspace_id: uuid.UUID, account_ids: list[uuid.UUID]
) -> list[uuid.UUID]:
    """The ids deduplicated, once each is known to be this workspace's account."""
    wanted = list(dict.fromkeys(account_ids))
    if not wanted:
        return []
    found = set(
        (
            await db.execute(
                select(LinkedInAccount.id).where(
                    LinkedInAccount.workspace_id == workspace_id,
                    LinkedInAccount.id.in_(wanted),
                )
            )
        ).scalars()
    )
    if len(found) != len(wanted):
        raise ValidationFailedError(
            "One of the selected LinkedIn accounts is not in this workspace"
        )
    return wanted


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
    db: AsyncSession,
    ctx: WorkspaceContext,
    title: str,
    content: str,
    enabled: bool,
    linkedin_account_ids: list[uuid.UUID] | None = None,
    assistant_ids: list[uuid.UUID] | None = None,
) -> KnowledgeItem:
    item = KnowledgeItem(
        workspace_id=ctx.workspace_id,
        title=title,
        content=content,
        enabled=enabled,
        linkedin_account_ids=await _check_accounts(
            db, ctx.workspace_id, linkedin_account_ids or []
        ),
        assistant_ids=await _check_assistants(db, ctx.workspace_id, assistant_ids or []),
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
    if patch.get("linkedin_account_ids") is not None:
        item.linkedin_account_ids = await _check_accounts(
            db, ctx.workspace_id, patch["linkedin_account_ids"]
        )
    if patch.get("assistant_ids") is not None:
        item.assistant_ids = await _check_assistants(
            db, ctx.workspace_id, patch["assistant_ids"]
        )
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
