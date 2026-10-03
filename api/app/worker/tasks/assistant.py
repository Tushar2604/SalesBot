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
from app.integrations import events as integration_events
from app.linkedin import caps as caps_mod
from app.linkedin import guard
from app.models.assistant import AssistantProfile
from app.models.campaigns import ActionTask, Campaign, CampaignLead, StepType, TaskStatus
from app.models.inbox import Conversation, Message, MessageAuthor, MessageDirection
from app.models.leads import Lead
from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus
from app.models.tenancy import NotificationType, Workspace
from app.scheduler import locks, pacing, quota
from app.services import notification_service
from app.services.assistant_service import (
    campaign_assistant_id,
    effective_settings,
    knowledge_query,
    resolve_settings,
)
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
    sending: bool = True,
) -> tuple[str, datetime | None]:
    """("", None) when the bot may act; else a reason, plus a retry time when
    the block is only temporary (someone is typing).

    With `sending` False the bot only proposes text for a person to send, so
    the pause and connection gates that protect automatic sending do not
    apply: a paused thread, or one on a disconnected account, still gets a
    suggested reply."""
    if cfg["mode"] == "off":
        return "assistant is off", None
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
    if not sending:
        return "", None
    if conversation.bot_paused:
        return f"paused: {conversation.bot_pause_reason or 'by you'}", None
    if not _account_connected(db, conversation):
        return "account is not connected", None
    return "", None


def _account_connected(db: Session, conversation: Conversation) -> bool:
    account = db.get(LinkedInAccount, conversation.linkedin_account_id)
    return (
        account is not None
        and account.status is LinkedInAccountStatus.ACTIVE
        and account.is_connected
    )


def _send_at(
    db: Session,
    conversation: Conversation,
    account: LinkedInAccount,
    cfg: dict[str, Any],
    now: datetime,
    received_at: datetime | None = None,
) -> datetime:
    """When this reply should go out.

    A fresh random wait per reply (3, then 7, then 5 minutes...), counted from
    when the prospect wrote rather than from when the inbox poll noticed it, so
    the poll interval does not stack on top of the chosen wait.

    Then spaced from everything else this account is doing: never before its
    next allowed action, and a random gap after any reply already scheduled in
    another thread — so five people answering at once get five replies a few
    minutes apart, never a burst.
    """
    minutes = random.uniform(cfg["reply_delay_min_minutes"], cfg["reply_delay_max_minutes"])  # noqa: S311
    start = received_at if received_at is not None and received_at <= now else now
    when = max(start + timedelta(minutes=minutes), now + timedelta(seconds=45))

    # The account's action gap (the same clock every part of the product uses).
    gap_ends = guard.earliest(account, now)
    if gap_ends > when:
        when = gap_ends + timedelta(seconds=random.randint(5, 45))  # noqa: S311
    planned = db.scalar(
        select(func.max(Conversation.bot_send_at)).where(
            Conversation.linkedin_account_id == account.id,
            Conversation.id != conversation.id,
            Conversation.bot_send_at.isnot(None),
            Conversation.bot_send_at > now - timedelta(minutes=2),
        )
    )
    if planned is not None:
        when = max(when, planned + timedelta(seconds=pacing.sample_gap_seconds()))

    if cfg["working_hours_only"] and not caps_mod.within_working_hours(account, now=when)[0]:
        when = pacing.schedule_within_working_hours(account, when)
    return when


def _account_gate(
    db: Session, account: LinkedInAccount, workspace: Workspace | None, now: datetime
) -> tuple[str, datetime | None]:
    """The account-level rules every campaign action obeys, applied to a bot
    send too: ("", None) to go ahead, a reason with a retry time to wait, or a
    reason alone to not send at all.

    Without this a bot reply ignored the per-account gap, so replies in several
    threads — or a reply right after a campaign invite — went out back to back.
    """
    if workspace is not None and workspace.outreach_paused:
        return "the workspace kill switch is on", None
    if account.circuit_is_open(now):
        return f"the account is paused: {account.circuit_reason or 'safety stop'}", None
    gap_ends = guard.earliest(account, now)
    if gap_ends > now:
        return "waiting for the account's action gap", (
            gap_ends + timedelta(seconds=random.randint(5, 45))  # noqa: S311
        )
    in_flight = db.scalar(
        select(func.count())
        .select_from(ActionTask)
        .where(
            ActionTask.linkedin_account_id == account.id,
            ActionTask.status == TaskStatus.DISPATCHED,
        )
    )
    if locks.is_held(account.id) or in_flight:
        return "the account is busy with another action", (
            now + timedelta(seconds=random.randint(60, 150))  # noqa: S311
        )
    return "", None


def _enrollment(db: Session, conversation: Conversation) -> CampaignLead | None:
    """The campaign enrollment this thread came from, if any."""
    enrollment = (
        db.get(CampaignLead, conversation.campaign_lead_id)
        if conversation.campaign_lead_id
        else None
    )
    if enrollment is None and conversation.lead_id:
        enrollment = db.execute(
            select(CampaignLead)
            .where(
                CampaignLead.lead_id == conversation.lead_id,
                CampaignLead.linkedin_account_id == conversation.linkedin_account_id,
            )
            .order_by(CampaignLead.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
    return enrollment


def _thread_settings(
    db: Session, conversation: Conversation, workspace: Workspace | None
) -> dict[str, Any]:
    """The settings this thread runs under: the workspace's, with the
    assistant its campaign picked laid over them (see `effective_settings`).
    A thread from no campaign, or one that picked none, gets the default."""
    base = resolve_settings((workspace.settings or {}).get("assistant") if workspace else None)
    enrollment = _enrollment(db, conversation)
    campaign = db.get(Campaign, enrollment.campaign_id) if enrollment is not None else None
    picked = campaign_assistant_id(campaign)
    profile = db.get(AssistantProfile, picked) if picked else None
    if profile is not None and profile.workspace_id != conversation.workspace_id:
        profile = None
    return effective_settings(base, profile)


def _outreach_context(
    db: Session, conversation: Conversation
) -> tuple[dict[str, str], str]:
    """Who this person is and why the owner reached out, for the model.

    Scoped to this one lead and the one campaign they came from, so a reply can
    answer "why did you contact me?" without ever drawing on another thread.
    """
    lead = db.get(Lead, conversation.lead_id) if conversation.lead_id else None
    profile: dict[str, str] = {}
    if lead is not None:
        profile = {
            "headline": lead.headline or "",
            "title": lead.title or "",
            "company": lead.company or "",
            "location": lead.location or "",
        }

    enrollment = _enrollment(db, conversation)
    if enrollment is None:
        return profile, ""

    campaign = db.get(Campaign, enrollment.campaign_id)
    if campaign is None:
        return profile, ""

    lines = [f"Campaign: {campaign.name}"]
    brief = str((campaign.settings or {}).get("ai_brief", "")).strip()
    lines.append(f"What it is about: {brief}" if brief else "What it is about: (no brief given)")
    note = db.execute(
        select(ActionTask.payload)
        .where(
            ActionTask.campaign_lead_id == enrollment.id,
            ActionTask.action_type == StepType.INVITE,
            ActionTask.status == TaskStatus.SUCCEEDED,
        )
        .order_by(ActionTask.finished_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if note and str(note.get("body") or "").strip():
        lines.append(f'Connection note the owner sent: "{str(note["body"]).strip()}"')
    return profile, "\n".join(lines)


def _recent_openers(db: Session, conversation: Conversation) -> list[str]:
    """How this account's recent automatic replies began, in other threads:
    the same opener across many conversations is what makes a bot obvious."""
    rows = db.execute(
        select(Message.body)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(
            Conversation.linkedin_account_id == conversation.linkedin_account_id,
            Message.conversation_id != conversation.id,
            Message.author == MessageAuthor.BOT.value,
        )
        .order_by(Message.sent_at.desc())
        .limit(15)
    ).scalars()
    return [ai.opener(body) for body in rows if body]


def _daily_message_budget_left(db: Session, account: LinkedInAccount, now: datetime) -> int:
    """Messages still allowed today. Campaign and inbox messages share one
    budget: LinkedIn counts everything the account sends, not just campaigns."""
    limit = caps_mod.resolve(account, now=now).daily_messages
    used = quota.used_today(db, account, StepType.MESSAGE, now=now) + quota.in_flight(
        db, account, StepType.MESSAGE
    )
    return limit - used


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
def respond(
    self: Any,
    conversation_id: str,
    follow_up: bool = False,
    draft_only: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Decide the next move in one conversation.

    draft_only  propose a reply but never schedule it, and ring no bell (the
                inbox sweep of older unanswered threads uses this)
    force       a person asked for a draft right now: skip the gates that only
                keep the bot from talking over them, and answer whoever wrote
                last — a reply to them, or a follow-up to us. Implies draft_only.
    """
    _ = self
    now = datetime.now(UTC)
    draft_only = draft_only or force
    with session_scope() as db:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None:
            return {"done": False, "reason": "not found"}
        workspace = db.get(Workspace, conversation.workspace_id)
        cfg = _thread_settings(db, conversation, workspace)

        latest = _latest(db, conversation.id)
        if force:
            if latest is None:
                return {"done": False, "reason": "nothing to answer"}
            follow_up = latest.direction is MessageDirection.OUTBOUND
        else:
            reason, retry_at = _blocked(
                db, conversation, cfg, now, follow_up=follow_up, sending=False
            )
            if retry_at is not None:
                respond.apply_async(
                    args=[conversation_id, follow_up, draft_only], eta=retry_at, queue="ai"
                )
                return {"done": False, "reason": reason, "retry_at": retry_at.isoformat()}
            if reason:
                return {"done": False, "reason": reason}
        assert latest is not None  # _blocked guarantees a latest message

        history = list(
            db.execute(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(Message.sent_at.desc(), Message.created_at.desc())
                .limit(30)
            ).scalars()
        )[::-1]
        # The SOPs for the account this thread is on and for the assistant its
        # campaign picked, plus the shared ones.
        knowledge = [
            ai.KnowledgeDoc(item.title, item.content)
            for item in db.execute(
                knowledge_query(
                    conversation.workspace_id,
                    conversation.linkedin_account_id,
                    cfg["assistant_id"],
                )
            ).scalars()
        ]
        profile, outreach = _outreach_context(db, conversation)
        decision = ai.decide(
            ai.AssistantConfig(
                cfg["persona"],
                cfg["instructions"],
                cfg["handoff_topics"],
                tuple(cfg["collect_fields"]),
            ),
            knowledge,
            [ai.Turn(m.direction is MessageDirection.OUTBOUND, m.body, m.author) for m in history],
            conversation.participant_name,
            follow_up=follow_up,
            known_facts=dict(conversation.bot_extracted or {}),
            recent_openers=_recent_openers(db, conversation),
            prospect_profile=profile,
            outreach_context=outreach,
        )
        if decision is None:
            return {"done": False, "reason": "no decision (check the AI provider keys and logs)"}

        _remember_facts(db, conversation, decision.shared_facts)
        name = conversation.participant_name or "a prospect"
        # Stamped whatever the decision, even when nothing is proposed: it
        # marks the latest message as handled, so the same thread is not sent
        # to the model again on every poll.
        conversation.bot_draft_at = now

        if follow_up:
            # A suggestion only: never sent automatically, and no bell for it.
            if decision.action == "reply":
                conversation.bot_draft = decision.reply
                return {"done": True, "action": "draft"}
            return {"done": True, "action": "no_reply"}

        if decision.action == "handoff":
            conversation.bot_paused = True
            conversation.bot_pause_reason = f"Needs you: {decision.handoff_reason}"[:200]
            conversation.bot_draft = ""
            conversation.bot_send_at = None
            _notify(
                db,
                conversation,
                f"{name} needs you",
                decision.handoff_reason or "The assistant handed this over.",
            )
            lead = db.get(Lead, conversation.lead_id) if conversation.lead_id else None
            integration_events.emit_sync(
                db,
                conversation.workspace_id,
                "assistant.handoff",
                {
                    "at": now.isoformat(),
                    "conversation_id": str(conversation.id),
                    "reason": decision.handoff_reason,
                    "collected": dict(conversation.bot_extracted or {}),
                    "lead": integration_events.lead_data(lead),
                },
            )
            return {"done": True, "action": "handoff"}
        if decision.action == "no_reply":
            conversation.bot_send_at = None
            return {"done": True, "action": "no_reply"}

        conversation.bot_draft = decision.reply
        if draft_only:
            conversation.bot_send_at = None
            return {"done": True, "action": "draft"}

        account = db.get(LinkedInAccount, conversation.linkedin_account_id)
        # Sending gates: when one is closed the reply stays a suggestion.
        auto_blocked, _ = _blocked(db, conversation, cfg, now)
        over_thread_cap = (
            _bot_count(db, now, conversation_id=conversation.id)
            >= cfg["max_replies_per_thread_per_day"]
        )
        over_account_cap = (
            account is not None
            and _bot_count(db, now, account_id=account.id) >= cfg["max_replies_per_account_per_day"]
        )
        if cfg["mode"] == "auto" and not auto_blocked and over_thread_cap:
            conversation.bot_paused = True
            conversation.bot_pause_reason = "Reached today's reply limit for this thread"
        if (
            cfg["mode"] == "draft"
            or auto_blocked
            or over_thread_cap
            or over_account_cap
            or account is None
        ):
            conversation.bot_send_at = None
            note = (
                " (daily auto-reply limit reached)" if over_thread_cap or over_account_cap else ""
            )
            _notify(db, conversation, f"Reply drafted for {name}{note}", decision.reply)
            return {"done": True, "action": "draft"}

        when = _send_at(db, conversation, account, cfg, now, latest.sent_at)
        conversation.bot_send_at = when
        send.apply_async(
            args=[conversation_id, decision.reply, str(latest.id)], eta=when, queue="ai"
        )
        return {"done": True, "action": "scheduled", "send_at": when.isoformat()}


@celery_app.task(name="assistant.send", bind=True, max_retries=0)
def send(self: Any, conversation_id: str, text: str, answered_message_id: str) -> dict[str, Any]:
    _ = self
    now = datetime.now(UTC)
    args = [conversation_id, text, answered_message_id]
    with session_scope() as db:
        # Row-locked: a long-ETA task can be delivered twice by the broker, and
        # both copies must not pass the "draft unchanged" check before either
        # has sent. The second waits here, then sees the draft already cleared.
        conversation = db.get(Conversation, conversation_id, with_for_update=True)
        if conversation is None:
            return {"sent": False, "reason": "not found"}
        workspace = db.get(Workspace, conversation.workspace_id)
        cfg = _thread_settings(db, conversation, workspace)

        def later(when: datetime, reason: str) -> dict[str, Any]:
            conversation.bot_send_at = when
            send.apply_async(args=args, eta=when, queue="ai")
            return {"sent": False, "reason": reason, "retry_at": when.isoformat()}

        def dropped(reason: str) -> dict[str, Any]:
            conversation.bot_send_at = None
            return {"sent": False, "reason": reason}

        if cfg["mode"] != "auto":
            return dropped("no longer in auto mode; kept as a draft")
        reason, retry_at = _blocked(db, conversation, cfg, now)
        if retry_at is not None:
            return later(retry_at, reason)
        if reason:
            return dropped(reason)
        latest = _latest(db, conversation.id)
        if latest is None or str(latest.id) != answered_message_id:
            # The prospect wrote again; the newer message gets its own decision.
            return {"sent": False, "reason": "superseded by a newer message"}
        if conversation.bot_draft != text:
            return dropped("draft was edited, sent or discarded")

        account = db.get(LinkedInAccount, conversation.linkedin_account_id)
        if account is None:
            return dropped("account missing")
        # Hard rules, checked at the moment of sending whatever the settings say.
        in_hours, _ = caps_mod.within_working_hours(account, now=now)
        if cfg["working_hours_only"] and not in_hours:
            next_window = pacing.schedule_within_working_hours(account, now)
            return later(next_window, "outside working hours")
        gate, gate_retry = _account_gate(db, account, workspace, now)
        if gate_retry is not None:
            return later(gate_retry, gate)
        if gate:
            _notify(
                db,
                conversation,
                f"Reply drafted for {conversation.participant_name or 'a prospect'} (not sent)",
                f"{gate}. {text}",
            )
            return dropped(f"{gate}; kept as a draft")
        if _daily_message_budget_left(db, account, now) <= 0:
            _notify(
                db,
                conversation,
                f"Reply drafted for {conversation.participant_name or 'a prospect'} "
                "(daily message limit reached)",
                text,
            )
            return dropped("daily message limit reached; kept as a draft")

        result = deliver_text(db, conversation, text, MessageAuthor.BOT.value)
        if not result["ok"] and result.get("reason") == "account busy":
            return later(now + timedelta(seconds=random.randint(60, 150)), "account busy")  # noqa: S311
        if not result["ok"] and result.get("reason") == "action gap":
            retry_at = datetime.fromisoformat(result["retry_at"])
            return later(retry_at + timedelta(seconds=random.randint(5, 45)), "action gap")  # noqa: S311
        if not result["ok"]:
            conversation.bot_send_at = None
        return {"sent": result["ok"], **result}
