"""The inbox assistant's two steps: decide, then (in auto mode) send.

    assistant.respond(conversation)          one Claude decision per new inbound
    assistant.send(conversation, text, msg)  delivers it after a human-like pause

Every gate is checked in `_blocked` — once when deciding and again right before
sending, because anything can change during the pause: the person may start
typing, reply themselves, pause the bot, or the prospect may write again. The
bot staying quiet is always the safe outcome, so any doubt means no send.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import assistant as ai
from app.core.logging import get_logger
from app.db import session_scope
from app.linkedin import caps as caps_mod
from app.models.assistant import KnowledgeItem
from app.models.inbox import Conversation, Message, MessageAuthor, MessageDirection
from app.models.leads import Lead
from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus
from app.models.tenancy import NotificationType, Workspace
from app.scheduler import pacing
from app.services import notification_service
from app.services.assistant_service import resolve_settings
from app.worker.celery_app import celery_app
from app.worker.tasks.sync import deliver_text

log = get_logger(__name__)

# How long to wait after the last keystroke signal before acting.
_TYPING_GRACE = timedelta(seconds=20)


def _latest(db: Session, conversation_id: Any) -> Message | None:
    return db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.sent_at.desc(), Message.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _bot_count(
    db: Session, now: datetime, *, conversation_id: Any = None, account_id: Any = None
) -> int:
    query = select(func.count(Message.id)).where(
        Message.author == MessageAuthor.BOT.value, Message.sent_at >= now - timedelta(days=1)
    )
    if conversation_id is not None:
        query = query.where(Message.conversation_id == conversation_id)
    if account_id is not None:
        query = query.join(Conversation, Conversation.id == Message.conversation_id).where(
            Conversation.linkedin_account_id == account_id
        )
    return int(db.execute(query).scalar_one())


def _blocked(
    db: Session,
    conversation: Conversation,
    cfg: dict[str, Any],
    now: datetime,
    *,
    follow_up: bool = False,
) -> tuple[str, datetime | None]:
    """("", None) when the bot may act; else a reason, plus a retry time when
    the block is only temporary (someone is typing).

    A follow-up only ever proposes text for a person to send, so the pause and
    connection gates that protect automatic sending do not apply to it."""
    if cfg["mode"] == "off":
        return "assistant is off", None
    if conversation.bot_paused and not follow_up:
        return f"paused: {conversation.bot_pause_reason or 'by you'}", None
    if conversation.snoozed_until and conversation.snoozed_until > now:
        return "conversation is snoozed", None
    if conversation.human_active_until and conversation.human_active_until > now:
        return "a person is typing", conversation.human_active_until + _TYPING_GRACE
    latest = _latest(db, conversation.id)
    wanted = MessageDirection.OUTBOUND if follow_up else MessageDirection.INBOUND
    if latest is None or latest.direction is not wanted:
        return "nothing new to answer", None
    if follow_up:
        stale = conversation.bot_draft or (
            conversation.bot_draft_at and conversation.bot_draft_at >= latest.sent_at
        )
        return ("already suggested a follow-up", None) if stale else ("", None)
    account = db.get(LinkedInAccount, conversation.linkedin_account_id)
    if (
        account is None
        or account.status is not LinkedInAccountStatus.ACTIVE
        or not account.is_connected
    ):
        return "account is not connected", None
    return "", None


def _send_at(account: LinkedInAccount, cfg: dict[str, Any], now: datetime) -> datetime:
    minutes = random.uniform(cfg["reply_delay_min_minutes"], cfg["reply_delay_max_minutes"])  # noqa: S311
    when = now + timedelta(minutes=minutes)
    if cfg["working_hours_only"] and not caps_mod.within_working_hours(account, now=when)[0]:
        when = pacing.schedule_within_working_hours(account, when)
    return when


def _notify(db: Session, conversation: Conversation, title: str, body: str) -> None:
    notification_service.create_sync(
        db,
        conversation.workspace_id,
        NotificationType.INBOX_REPLY,
        title,
        body=body[:180],
        link=f"/inbox?conversation={conversation.id}",
    )


def _remember_facts(db: Session, conversation: Conversation, facts: list[ai.SharedFact]) -> None:
    if not facts:
        return
    found = {
        f.field.strip().lower()[:60]: f.value.strip()[:500]
        for f in facts
        if f.field.strip() and f.value.strip()
    }
    conversation.bot_extracted = {**(conversation.bot_extracted or {}), **found}
    if conversation.lead_id:
        lead = db.get(Lead, conversation.lead_id)
        if lead is not None:
            enriched = dict(lead.enriched or {})
            enriched["shared"] = {**enriched.get("shared", {}), **found}
            lead.enriched = enriched
            if not lead.email and "email" in found and "@" in found["email"]:
                lead.email = found["email"][:320]


@celery_app.task(name="assistant.respond", bind=True, max_retries=0)
def respond(self: Any, conversation_id: str, follow_up: bool = False) -> dict[str, Any]:
    _ = self
    now = datetime.now(UTC)
    with session_scope() as db:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None:
            return {"done": False, "reason": "not found"}
        workspace = db.get(Workspace, conversation.workspace_id)
        cfg = resolve_settings((workspace.settings or {}).get("assistant") if workspace else None)

        reason, retry_at = _blocked(db, conversation, cfg, now, follow_up=follow_up)
        if retry_at is not None:
            respond.apply_async(args=[conversation_id, follow_up], eta=retry_at, queue="ai")
            return {"done": False, "reason": reason, "retry_at": retry_at.isoformat()}
        if reason:
            return {"done": False, "reason": reason}

        latest = _latest(db, conversation.id)
        assert latest is not None  # _blocked guarantees an inbound latest message

        if (
            _bot_count(db, now, conversation_id=conversation.id)
            >= cfg["max_replies_per_thread_per_day"]
        ):
            conversation.bot_paused = True
            conversation.bot_pause_reason = "Reached today's reply limit for this thread"
            _notify(
                db,
                conversation,
                f"Assistant paused for {conversation.participant_name or 'a conversation'}",
                "It reached today's reply limit here. Reply yourself or resume it tomorrow.",
            )
            return {"done": False, "reason": "thread limit"}

        history = list(
            db.execute(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.sent_at.desc(), Message.created_at.desc())
                .limit(30)
            ).scalars()
        )[::-1]
        knowledge = [
            ai.KnowledgeDoc(item.title, item.content)
            for item in db.execute(
                select(KnowledgeItem)
                .where(
                    KnowledgeItem.workspace_id == conversation.workspace_id,
                    KnowledgeItem.enabled.is_(True),
                )
                .order_by(KnowledgeItem.created_at)
            ).scalars()
        ]
        decision = ai.decide(
            ai.AssistantConfig(cfg["persona"], cfg["instructions"], cfg["handoff_topics"]),
            knowledge,
            [ai.Turn(m.direction is MessageDirection.OUTBOUND, m.body, m.author) for m in history],
            conversation.participant_name,
            follow_up=follow_up,
        )
        if decision is None:
            return {"done": False, "reason": "no decision (check the Anthropic key and logs)"}

        _remember_facts(db, conversation, decision.shared_facts)
        name = conversation.participant_name or "a prospect"

        if follow_up:
            # A suggestion only: never sent automatically, and no bell for it.
            # bot_draft_at is stamped even when nothing is proposed, so the
            # same silent thread is not sent to the model on every poll.
            conversation.bot_draft_at = now
            if decision.action == "reply":
                conversation.bot_draft = decision.reply
                return {"done": True, "action": "draft"}
            return {"done": True, "action": "no_reply"}

        if decision.action == "handoff":
            conversation.bot_paused = True
            conversation.bot_pause_reason = f"Needs you: {decision.handoff_reason}"[:200]
            conversation.bot_draft = ""
            _notify(
                db,
                conversation,
                f"{name} needs you",
                decision.handoff_reason or "The assistant handed this over.",
            )
            return {"done": True, "action": "handoff"}
        if decision.action == "no_reply":
            return {"done": True, "action": "no_reply"}

        conversation.bot_draft = decision.reply
        conversation.bot_draft_at = now
        account = db.get(LinkedInAccount, conversation.linkedin_account_id)
        over_account_cap = (
            account is not None
            and _bot_count(db, now, account_id=account.id) >= cfg["max_replies_per_account_per_day"]
        )
        if cfg["mode"] == "draft" or over_account_cap or account is None:
            note = " (daily auto-reply limit reached)" if over_account_cap else ""
            _notify(db, conversation, f"Reply drafted for {name}{note}", decision.reply)
            return {"done": True, "action": "draft"}

        when = _send_at(account, cfg, now)
        send.apply_async(
            args=[conversation_id, decision.reply, str(latest.id)], eta=when, queue="ai"
        )
        return {"done": True, "action": "scheduled", "send_at": when.isoformat()}


@celery_app.task(name="assistant.send", bind=True, max_retries=0)
def send(self: Any, conversation_id: str, text: str, answered_message_id: str) -> dict[str, Any]:
    _ = self
    now = datetime.now(UTC)
    with session_scope() as db:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None:
            return {"sent": False, "reason": "not found"}
        workspace = db.get(Workspace, conversation.workspace_id)
        cfg = resolve_settings((workspace.settings or {}).get("assistant") if workspace else None)

        if cfg["mode"] != "auto":
            return {"sent": False, "reason": "no longer in auto mode; kept as a draft"}
        reason, retry_at = _blocked(db, conversation, cfg, now)
        if retry_at is not None:
            send.apply_async(
                args=[conversation_id, text, answered_message_id], eta=retry_at, queue="ai"
            )
            return {"sent": False, "reason": reason}
        if reason:
            return {"sent": False, "reason": reason}
        latest = _latest(db, conversation.id)
        if latest is None or str(latest.id) != answered_message_id:
            # The prospect wrote again; the newer message gets its own decision.
            return {"sent": False, "reason": "superseded by a newer message"}
        if conversation.bot_draft != text:
            return {"sent": False, "reason": "draft was edited or discarded"}

        result = deliver_text(db, conversation, text, MessageAuthor.BOT.value)
        if not result["ok"] and result.get("reason") == "account busy":
            send.apply_async(
                args=[conversation_id, text, answered_message_id], countdown=90, queue="ai"
            )
        return {"sent": result["ok"], **result}
