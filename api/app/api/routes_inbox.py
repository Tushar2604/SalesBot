"""Inbox endpoints: browse LinkedIn conversations, label, snooze, reply.

Sending is the one write that leaves this process — it is dispatched to a
worker (`linkedin.action.send_reply`) rather than performed here, since the
LinkedIn driver is synchronous and must run inside the account's execution
lock, neither of which belongs in an async route.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.deps import Workspace_
from app.models.inbox import Conversation, ConversationLabel
from app.models.leads import Lead
from app.models.linkedin import LinkedInAccount
from app.models.tenancy import WorkspaceRole
from app.schemas.assistant import BotControlRequest, SendDraftRequest
from app.schemas.inbox import (
    ConversationPage,
    ConversationResponse,
    LabelRequest,
    MessageResponse,
    SendReplyRequest,
    SnoozeRequest,
)
from app.services import inbox_service
from app.worker.celery_app import celery_app

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["inbox"])


def _to_response(
    conversation: Conversation, account: LinkedInAccount, lead: Lead | None
) -> ConversationResponse:
    return ConversationResponse(
        id=conversation.id,
        linkedin_account_id=account.id,
        linkedin_account_label=account.label,
        lead_id=lead.id if lead else None,
        lead_name=(lead.full_name or lead.public_id) if lead else conversation.participant_name,
        lead_public_id=lead.public_id if lead else "",
        campaign_lead_id=conversation.campaign_lead_id,
        participant_urn=conversation.participant_urn,
        participant_name=conversation.participant_name,
        last_message_at=conversation.last_message_at,
        last_message_text=conversation.last_message_text,
        last_message_from_me=conversation.last_message_from_me,
        unread=conversation.unread,
        label=conversation.label,
        label_source=conversation.label_source,
        snoozed_until=conversation.snoozed_until,
        created_at=conversation.created_at,
        bot_paused=conversation.bot_paused,
        bot_pause_reason=conversation.bot_pause_reason,
        bot_draft=conversation.bot_draft,
        bot_draft_at=conversation.bot_draft_at,
        bot_extracted={str(k): str(v) for k, v in (conversation.bot_extracted or {}).items()},
    )


@router.get("/conversations", response_model=ConversationPage)
async def list_conversations(
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
    label: ConversationLabel | None = None,
    unread_only: bool = False,
    account_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConversationPage:
    rows, total = await inbox_service.list_conversations(
        db,
        ctx.workspace_id,
        label=label,
        unread_only=unread_only,
        account_id=account_id,
        limit=limit,
        offset=offset,
    )
    return ConversationPage(
        items=[_to_response(c, a, lead) for c, a, lead in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> ConversationResponse:
    conversation, account, lead = await inbox_service.get_conversation(
        db, ctx.workspace_id, conversation_id
    )
    return _to_response(conversation, account, lead)


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
async def list_messages(
    conversation_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> list[MessageResponse]:
    messages = await inbox_service.list_messages(db, ctx.workspace_id, conversation_id)
    return [MessageResponse.model_validate(m) for m in messages]


@router.post("/conversations/{conversation_id}/reply", response_model=ConversationResponse)
async def reply(
    conversation_id: uuid.UUID,
    payload: SendReplyRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationResponse:
    ctx.require_role(WorkspaceRole.MEMBER)
    conversation = await inbox_service.prepare_reply(db, ctx, conversation_id, payload.text)
    # A person is handling this thread now; the assistant steps back until resumed.
    conversation.bot_paused = True
    conversation.bot_pause_reason = "You replied yourself"
    conversation.bot_draft = ""

    # Commit before enqueueing: the worker must be able to see this row.
    await db.commit()
    celery_app.send_task(
        "linkedin.action.send_reply",
        args=[str(conversation.id), payload.text],
        queue="linkedin.action",
    )

    account = await db.get(LinkedInAccount, conversation.linkedin_account_id)
    lead = await db.get(Lead, conversation.lead_id) if conversation.lead_id else None
    return _to_response(conversation, account, lead)  # type: ignore[arg-type]


@router.post(
    "/conversations/{conversation_id}/label",
    response_model=ConversationResponse,
    status_code=status.HTTP_200_OK,
)
async def label(
    conversation_id: uuid.UUID,
    payload: LabelRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationResponse:
    ctx.require_role(WorkspaceRole.MEMBER)
    conversation, account, lead = await inbox_service.set_label(
        db, ctx, conversation_id, payload.label
    )
    return _to_response(conversation, account, lead)


@router.post("/conversations/{conversation_id}/snooze", response_model=ConversationResponse)
async def snooze(
    conversation_id: uuid.UUID,
    payload: SnoozeRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationResponse:
    ctx.require_role(WorkspaceRole.MEMBER)
    conversation, account, lead = await inbox_service.snooze(
        db, ctx, conversation_id, payload.until
    )
    return _to_response(conversation, account, lead)


@router.post("/conversations/{conversation_id}/read", response_model=ConversationResponse)
async def mark_read(
    conversation_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> ConversationResponse:
    ctx.require_role(WorkspaceRole.MEMBER)
    conversation, account, lead = await inbox_service.mark_read(db, ctx, conversation_id)
    return _to_response(conversation, account, lead)


# ── AI assistant controls ────────────────────────────────────────────────────

# How long one "typing" signal holds the assistant off. The inbox re-sends it
# every few seconds while someone is typing, so it lapses soon after they stop.
_TYPING_HOLD = timedelta(seconds=90)


@router.post("/conversations/{conversation_id}/typing", status_code=status.HTTP_204_NO_CONTENT)
async def typing(
    conversation_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> None:
    """A person is writing in this thread: the assistant must not talk over them."""
    ctx.require_role(WorkspaceRole.MEMBER)
    conversation, _account, _lead = await inbox_service.get_conversation(
        db, ctx.workspace_id, conversation_id
    )
    conversation.human_active_until = datetime.now(UTC) + _TYPING_HOLD
    await db.commit()


@router.post("/conversations/{conversation_id}/bot", response_model=ConversationResponse)
async def bot_control(
    conversation_id: uuid.UUID,
    payload: BotControlRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationResponse:
    """Pause or resume the assistant in one thread. Resuming answers any
    unanswered message straight away."""
    ctx.require_role(WorkspaceRole.MEMBER)
    conversation, account, lead = await inbox_service.get_conversation(
        db, ctx.workspace_id, conversation_id
    )
    conversation.bot_paused = payload.paused
    # Pausing keeps any draft visible as a suggestion; it just will not be sent
    # automatically (the send step refuses while the thread is paused).
    conversation.bot_pause_reason = "Paused by you" if payload.paused else ""
    await db.commit()
    if not payload.paused:
        celery_app.send_task("assistant.respond", args=[str(conversation.id)], queue="ai")
    return _to_response(conversation, account, lead)


@router.post("/conversations/{conversation_id}/bot/send-draft", response_model=ConversationResponse)
async def send_draft(
    conversation_id: uuid.UUID,
    payload: SendDraftRequest,
    ctx: Workspace_,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationResponse:
    """Send the assistant's draft (possibly edited). Unlike a hand-written
    reply, this keeps the assistant active in the thread."""
    ctx.require_role(WorkspaceRole.MEMBER)
    conversation = await inbox_service.prepare_reply(db, ctx, conversation_id, payload.text)
    await db.commit()
    celery_app.send_task(
        "linkedin.action.send_reply",
        args=[str(conversation.id), payload.text, "bot"],
        queue="linkedin.action",
    )
    account = await db.get(LinkedInAccount, conversation.linkedin_account_id)
    lead = await db.get(Lead, conversation.lead_id) if conversation.lead_id else None
    return _to_response(conversation, account, lead)  # type: ignore[arg-type]


@router.post(
    "/conversations/{conversation_id}/bot/discard-draft", response_model=ConversationResponse
)
async def discard_draft(
    conversation_id: uuid.UUID, ctx: Workspace_, db: Annotated[AsyncSession, Depends(get_db)]
) -> ConversationResponse:
    ctx.require_role(WorkspaceRole.MEMBER)
    conversation, account, lead = await inbox_service.get_conversation(
        db, ctx.workspace_id, conversation_id
    )
    conversation.bot_draft = ""
    conversation.bot_draft_at = None
    await db.commit()
    return _to_response(conversation, account, lead)
