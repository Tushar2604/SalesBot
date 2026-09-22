"""Reading and acting on conversations.

Nothing here talks to LinkedIn. Sending a reply needs the sync driver and the
account's execution slot, so a route only validates and dispatches a worker
task (`linkedin.action.send_reply`, in `app.worker.tasks.sync`) — exactly how
connecting an account works in `routes_linkedin.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError, ValidationFailedError
from app.deps import WorkspaceContext
from app.models.inbox import Conversation, ConversationLabel, LabelSource, Message
from app.models.leads import Lead
from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus
from app.services import audit


async def list_conversations(
    db: AsyncSession,
    workspace_id: uuid.UUID,
    *,
    label: ConversationLabel | None = None,
    unread_only: bool = False,
    account_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[tuple[Conversation, LinkedInAccount, Lead | None]], int]:
    conditions = [Conversation.workspace_id == workspace_id]
    if label is not None:
        conditions.append(Conversation.label == label)
    if unread_only:
        conditions.append(Conversation.unread.is_(True))
    if account_id is not None:
        conditions.append(Conversation.linkedin_account_id == account_id)

    total = (
        await db.scalar(select(func.count()).select_from(Conversation).where(*conditions))
    ) or 0

    rows = (
        await db.execute(
            select(Conversation, LinkedInAccount, Lead)
            .join(LinkedInAccount, LinkedInAccount.id == Conversation.linkedin_account_id)
            .outerjoin(Lead, Lead.id == Conversation.lead_id)
            .where(*conditions)
            .order_by(Conversation.last_message_at.desc().nulls_last())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    return [(c, a, lead) for c, a, lead in rows], total


async def _get_with_account(
    db: AsyncSession, workspace_id: uuid.UUID, conversation_id: uuid.UUID
) -> tuple[Conversation, LinkedInAccount, Lead | None]:
    row = (
        await db.execute(
            select(Conversation, LinkedInAccount, Lead)
            .join(LinkedInAccount, LinkedInAccount.id == Conversation.linkedin_account_id)
            .outerjoin(Lead, Lead.id == Conversation.lead_id)
            .where(Conversation.id == conversation_id, Conversation.workspace_id == workspace_id)
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("conversation not found")
    return row


async def get_conversation(
    db: AsyncSession, workspace_id: uuid.UUID, conversation_id: uuid.UUID
) -> tuple[Conversation, LinkedInAccount, Lead | None]:
    return await _get_with_account(db, workspace_id, conversation_id)


async def list_messages(
    db: AsyncSession, workspace_id: uuid.UUID, conversation_id: uuid.UUID
) -> list[Message]:
    # Confirms the conversation belongs to this workspace before returning
    # any of its messages.
    await _get_with_account(db, workspace_id, conversation_id)
    return list(
        (
            await db.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.sent_at)
            )
        )
        .scalars()
        .all()
    )


async def set_label(
    db: AsyncSession, ctx: WorkspaceContext, conversation_id: uuid.UUID, label: ConversationLabel
) -> tuple[Conversation, LinkedInAccount, Lead | None]:
    conversation, account, lead = await _get_with_account(db, ctx.workspace_id, conversation_id)
    conversation.label = label
    conversation.label_source = LabelSource.MANUAL

    await audit.record(
        db,
        "inbox.label_set",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="conversation",
        target_id=conversation.id,
        metadata={"label": label.value},
    )
    return conversation, account, lead


async def snooze(
    db: AsyncSession, ctx: WorkspaceContext, conversation_id: uuid.UUID, until: datetime | None
) -> tuple[Conversation, LinkedInAccount, Lead | None]:
    conversation, account, lead = await _get_with_account(db, ctx.workspace_id, conversation_id)
    conversation.snoozed_until = until

    await audit.record(
        db,
        "inbox.snoozed" if until else "inbox.unsnoozed",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="conversation",
        target_id=conversation.id,
        metadata={"until": until.isoformat() if until else None},
    )
    return conversation, account, lead


async def mark_read(
    db: AsyncSession, ctx: WorkspaceContext, conversation_id: uuid.UUID
) -> tuple[Conversation, LinkedInAccount, Lead | None]:
    # Local read-state only — not synced back to LinkedIn's own unread flag.
    # Not audited: read/unread churn is too frequent to be a meaningful trail.
    conversation, account, lead = await _get_with_account(db, ctx.workspace_id, conversation_id)
    conversation.unread = False
    return conversation, account, lead


async def prepare_reply(
    db: AsyncSession, ctx: WorkspaceContext, conversation_id: uuid.UUID, text: str
) -> Conversation:
    """Validates the send is possible; the route dispatches the actual send.

    Sending needs the sync driver and the account's execution slot, both of
    which only exist in a Celery worker — this only checks the account is in
    a state where a send could plausibly succeed.
    """
    conversation, account, _lead = await _get_with_account(db, ctx.workspace_id, conversation_id)
    if account.status is not LinkedInAccountStatus.ACTIVE or not account.is_connected:
        raise ValidationFailedError("this account is not connected; reconnect it to reply")

    await audit.record(
        db,
        "inbox.reply_queued",
        workspace_id=ctx.workspace_id,
        actor_user_id=ctx.user.id,
        target_type="conversation",
        target_id=conversation.id,
        metadata={"length": len(text)},
    )
    return conversation
