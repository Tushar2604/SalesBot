"""Inbound state: replies and invite acceptances.

These are reads, but they are the reason the product is not obnoxious. Reply
detection is what stops a sequence mid-flight, and it is the single most
requested behaviour in this category — nobody wants the "great to connect!"
follow-up arriving after the prospect already answered.

Both tasks hold the account's execution slot, because they are still requests
from that account and must not overlap with an outbound action.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.core.logging import get_logger
from app.db import session_scope
from app.linkedin import build_driver, health
from app.linkedin.driver import ConnectionStatus, ConversationSnapshot
from app.linkedin.voyager import extract_profile_id
from app.models.campaigns import (
    ActionTask,
    Campaign,
    CampaignLead,
    CampaignLeadEvent,
    ConnectionState,
    EnrollmentState,
    EventType,
    TaskStatus,
)
from app.models.inbox import Conversation, Message, MessageAuthor, MessageDirection
from app.models.leads import Lead
from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus
from app.models.tenancy import NotificationType
from app.scheduler import dispatcher, locks, pacing
from app.services import notification_service, tracking
from app.worker.celery_app import celery_app

log = get_logger(__name__)

# Invites younger than this are not polled: acceptance within minutes is rare
# and polling immediately just spends requests.
ACCEPTANCE_MIN_AGE = timedelta(minutes=settings.linkedin_acceptance_min_age_minutes)
ACCEPTANCE_BATCH = 15
CONVERSATION_PAGE = 30


def _active_enrollments_by_profile(db: Session, account_id: Any) -> dict[str, list[CampaignLead]]:
    """Maps a LinkedIn profile id to this account's live enrollments.

    Keyed on the extracted URN id, because a conversation participant and a
    stored lead URN use different URN prefixes for the same person.
    """
    rows = db.execute(
        select(CampaignLead, Lead)
        .join(Lead, Lead.id == CampaignLead.lead_id)
        .where(
            CampaignLead.linkedin_account_id == account_id,
            CampaignLead.state.in_([EnrollmentState.PENDING, EnrollmentState.RUNNING]),
        )
    ).all()

    index: dict[str, list[CampaignLead]] = {}
    for enrollment, lead in rows:
        for identifier in (lead.linkedin_urn, lead.public_id):
            if not identifier:
                continue
            index.setdefault(extract_profile_id(identifier).lower(), []).append(enrollment)
    return index


def _lead_by_name(leads_index: dict[str, Lead], name: str) -> Lead | None:
    """A lead whose full name is `name`, only if exactly one lead matches.

    LinkedIn identifies people by member id while leads are stored by vanity
    slug, so the first time we see a conversation the name is the bridge.
    Ambiguity returns None: linking a reply to the wrong lead would stop the
    wrong sequence.
    """
    wanted = " ".join(name.lower().split())
    if not wanted:
        return None
    matches = {
        id(lead): lead
        for lead in leads_index.values()
        if " ".join(f"{lead.first_name} {lead.last_name}".lower().split()) == wanted
    }
    return next(iter(matches.values())) if len(matches) == 1 else None


def _leads_by_profile(db: Session, workspace_id: Any) -> dict[str, Lead]:
    """Maps a LinkedIn profile id to a workspace's lead, for inbox linking.

    Unlike `_active_enrollments_by_profile`, this covers every lead in the
    workspace regardless of enrollment state — a conversation can exist for a
    lead whose sequence already finished or was never started.
    """
    leads = db.execute(select(Lead).where(Lead.workspace_id == workspace_id)).scalars().all()
    index: dict[str, Lead] = {}
    for lead in leads:
        for identifier in (
            lead.linkedin_urn,
            lead.public_id,
            (lead.enriched or {}).get("member_id", ""),
        ):
            if not identifier:
                continue
            index.setdefault(extract_profile_id(identifier).lower(), lead)
    return index


def _same_text(a: str, b: str) -> bool:
    """LinkedIn re-renders whitespace, so compare text with it collapsed."""
    return " ".join(a.split()) == " ".join(b.split())


def _is_campaign_text(db: Session, account_id: Any, text: str, now: datetime) -> bool:
    """True when a recent campaign step sent exactly this text (a note or message)."""
    bodies = db.execute(
        select(ActionTask.payload["body"].astext).where(
            ActionTask.linkedin_account_id == account_id,
            ActionTask.status == TaskStatus.SUCCEEDED,
            ActionTask.finished_at >= now - timedelta(days=30),
        )
    ).scalars()
    return any(body and _same_text(body, text) for body in bodies)


def _ingest_conversation(
    db: Session,
    account: LinkedInAccount,
    conversation: ConversationSnapshot,
    lead: Lead | None,
    campaign_lead: CampaignLead | None,
    now: datetime,
) -> list[Message]:
    """Upserts the thread and any new messages. Returns newly inserted messages.

    Idempotent: re-polling the same thread updates the row in place and only
    inserts messages not already stored (matched by the remote event id when
    LinkedIn gave one, otherwise by timestamp+direction+body).

    An outbound message nothing in this app sent — someone typed it on
    LinkedIn directly — pauses the assistant in this thread: a person is
    handling it now.
    """
    row = db.execute(
        select(Conversation).where(
            Conversation.linkedin_account_id == account.id,
            Conversation.conversation_urn == conversation.conversation_urn,
        )
    ).scalar_one_or_none()

    is_new_row = row is None
    if row is None:
        row = Conversation(
            workspace_id=account.workspace_id,
            linkedin_account_id=account.id,
            conversation_urn=conversation.conversation_urn,
        )
        db.add(row)

    row.participant_urn = conversation.participant_urn
    row.participant_name = conversation.participant_name or row.participant_name
    row.last_message_at = conversation.last_activity_at or row.last_message_at
    row.last_message_text = conversation.last_message_text
    row.last_message_from_me = conversation.last_message_from_me
    # Read state is local: LinkedIn marks a thread read as soon as this poll opens
    # it, so its flag must never clear what the person hasn't seen in the inbox.
    row.unread = row.unread or conversation.unread
    if lead is not None:
        row.lead_id = lead.id
    if campaign_lead is not None:
        row.campaign_lead_id = campaign_lead.id
    db.flush()  # assigns row.id for a brand-new conversation

    existing = db.execute(
        select(Message.remote_event_urn, Message.sent_at, Message.direction, Message.body).where(
            Message.conversation_id == row.id
        )
    ).all()
    # Messages this app sent that LinkedIn has not echoed back yet: adopt the
    # echo instead of storing the same message twice.
    unconfirmed = list(
        db.execute(
            select(Message).where(
                Message.conversation_id == row.id,
                Message.direction == MessageDirection.OUTBOUND,
                Message.remote_event_urn == "",
                Message.author != "",
            )
        ).scalars()
    )
    known_urns = {r.remote_event_urn for r in existing if r.remote_event_urn}
    known_fallback = {(r.sent_at, r.direction, r.body) for r in existing if not r.remote_event_urn}

    inserted: list[Message] = []
    for event in conversation.events:
        direction = MessageDirection.OUTBOUND if event.from_me else MessageDirection.INBOUND
        sent_at = event.sent_at or conversation.last_activity_at or now

        if event.event_urn:
            if event.event_urn in known_urns:
                # Self-heal: rows stored before direction was read reliably.
                db.execute(
                    update(Message)
                    .where(
                        Message.conversation_id == row.id,
                        Message.remote_event_urn == event.event_urn,
                        Message.direction != direction,
                        Message.author == "",
                    )
                    .values(direction=direction)
                )
                continue
        elif (sent_at, direction, event.text) in known_fallback:
            continue

        author = ""
        if direction is MessageDirection.OUTBOUND:
            mine = next((m for m in unconfirmed if _same_text(m.body, event.text)), None)
            if mine is not None:
                mine.remote_event_urn = event.event_urn
                unconfirmed.remove(mine)
                if event.event_urn:
                    known_urns.add(event.event_urn)
                continue
            if _is_campaign_text(db, account.id, event.text, now):
                author = MessageAuthor.CAMPAIGN.value
            elif not is_new_row and not row.bot_paused:
                # Brand-new rows carry old history, so only a message that
                # appeared since the last poll means someone is typing on
                # LinkedIn itself.
                row.bot_paused = True
                row.bot_pause_reason = "You messaged them on LinkedIn directly"
                row.bot_draft = ""
                log.info("assistant.paused_human_on_linkedin", conversation_id=str(row.id))

        message = Message(
            workspace_id=account.workspace_id,
            conversation_id=row.id,
            remote_event_urn=event.event_urn,
            direction=direction,
            body=event.text,
            sent_at=sent_at,
            author=author,
        )
        db.add(message)
        inserted.append(message)
        if event.event_urn:
            known_urns.add(event.event_urn)
        else:
            known_fallback.add((sent_at, direction, event.text))

    if any(m.direction is MessageDirection.INBOUND for m in inserted):
        row.unread = True
    if inserted:
        db.flush()  # assigns ids so callers can dispatch classification by id
    return inserted


def _conversation_id(db: Session, account_id: Any, conversation_urn: str) -> str | None:
    found = db.execute(
        select(Conversation.id).where(
            Conversation.linkedin_account_id == account_id,
            Conversation.conversation_urn == conversation_urn,
        )
    ).scalar_one_or_none()
    return str(found) if found else None


@celery_app.task(name="linkedin.sync.poll_replies", bind=True, max_retries=0)
def poll_replies(self: Any, account_id: str) -> dict[str, int]:
    """Finds inbound messages and stops those leads' sequences."""
    _ = self
    now = datetime.now(UTC)
    stopped = 0

    with session_scope() as db:
        account = db.get(LinkedInAccount, account_id)
        if account is None or account.status is not LinkedInAccountStatus.ACTIVE:
            return {"stopped": 0, "skipped": 1}
        if not account.is_connected:
            return {"stopped": 0, "skipped": 1}

        try:
            with locks.account_slot(account.id):
                driver = build_driver(account)
                try:
                    classification, conversations = driver.list_conversations(
                        limit=CONVERSATION_PAGE
                    )
                finally:
                    driver.close()
        except locks.SlotBusy:
            return {"stopped": 0, "skipped": 1}

        if not classification.ok:
            outcome = health.apply_classification(account, classification, now=now)
            if outcome.circuit_opened:
                dispatcher.pause_account_work(db, account.id, outcome.detail)
                who = account.label or account.public_id or "A LinkedIn account"
                notification_service.create_sync(
                    db,
                    account.workspace_id,
                    NotificationType.ACCOUNT_ACTION_NEEDED,
                    f"{who} stopped — {outcome.status.value.replace('_', ' ')}",
                    body=outcome.detail
                    or "Outreach from this account is paused until you reconnect it.",
                    link="/accounts",
                )
            return {"stopped": 0, "error": 1}

        health.apply_classification(account, classification, now=now)
        index = _active_enrollments_by_profile(db, account.id)
        leads_index = _leads_by_profile(db, account.workspace_id)
        new_inbound_message_ids: list[Any] = []
        conversations_to_answer: set[str] = set()
        conversations_to_follow_up: set[str] = set()

        for conversation in conversations:
            key = extract_profile_id(conversation.participant_urn).lower()

            # Persist the thread and any new messages regardless of who sent
            # last — the inbox shows the whole conversation, not just replies.
            lead = leads_index.get(key)
            if lead is None:
                lead = _lead_by_name(leads_index, conversation.participant_name)
                if lead is not None and conversation.participant_urn:
                    # Remember LinkedIn's member id so later polls match exactly.
                    lead.enriched = {
                        **(lead.enriched or {}),
                        "member_id": conversation.participant_urn,
                    }
            if lead is not None:
                # Enrollments are indexed by the lead's own profile id, so look
                # them up by that regardless of how the lead was matched.
                key = extract_profile_id(lead.public_id or lead.linkedin_urn).lower()
            enrollments = index.get(key, [])
            campaign_lead = enrollments[0] if enrollments else None
            inserted = _ingest_conversation(db, account, conversation, lead, campaign_lead, now)
            new_inbound = [m for m in inserted if m.direction is MessageDirection.INBOUND]
            new_inbound_message_ids.extend(m.id for m in new_inbound)
            conversations_to_answer.update(str(m.conversation_id) for m in new_inbound)

            if new_inbound:
                who = conversation.participant_name or "A prospect"
                notification_service.create_sync(
                    db,
                    account.workspace_id,
                    NotificationType.INBOX_REPLY,
                    f"New reply from {who}",
                    body=new_inbound[-1].body[:180],
                    link=f"/inbox?conversation={new_inbound[-1].conversation_id}",
                )

            # Only inbound messages count. Our own last message is not a reply.
            if conversation.last_message_from_me:
                thread_id = _conversation_id(db, account.id, conversation.conversation_urn)
                if thread_id:
                    conversations_to_follow_up.add(thread_id)
                continue
            for enrollment in enrollments:
                if enrollment.replied_at is not None:
                    continue
                enrollment.replied_at = conversation.last_activity_at or now
                tracking.log_event(enrollment, EventType.REPLIED, at=enrollment.replied_at)

                campaign = db.get(Campaign, enrollment.campaign_id)
                if campaign is not None and campaign.stop_on_reply:
                    enrollment.state = EnrollmentState.REPLIED
                    enrollment.next_run_at = None
                    enrollment.completed_at = now
                    enrollment.stopped_reason = "the prospect replied"
                    stopped += 1
                    log.info(
                        "sync.reply_stopped_sequence",
                        enrollment_id=str(enrollment.id),
                        campaign_id=str(enrollment.campaign_id),
                    )

        # No pacing reset here: reading the inbox is not an action, and pushing the
        # next-allowed time out every poll starved real actions (an invite never got
        # its turn). The account's single slot already stops a poll overlapping one.

    # Fired after the session commits, so the worker task can actually see
    # the message row it's being asked to classify.
    for message_id in new_inbound_message_ids:
        celery_app.send_task("ai.classify_message", args=[str(message_id)], queue="ai")
    for conversation_id in conversations_to_answer:
        celery_app.send_task("assistant.respond", args=[conversation_id], queue="ai")
    # The task decides whether a follow-up is due; it returns early when one
    # was already suggested for the latest message.
    for conversation_id in conversations_to_follow_up - conversations_to_answer:
        celery_app.send_task("assistant.respond", args=[conversation_id, True], queue="ai")

    return {"stopped": stopped, "conversations": len(conversations)}


def _previous_observation(db: Session, enrollment_id: Any) -> str:
    """What the last invite check saw for this lead ("" if there was none)."""
    event = db.execute(
        select(CampaignLeadEvent)
        .where(
            CampaignLeadEvent.campaign_lead_id == enrollment_id,
            CampaignLeadEvent.event_type == EventType.INVITE_STILL_PENDING.value,
        )
        .order_by(CampaignLeadEvent.occurred_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return str((event.meta or {}).get("observed", "")) if event else ""


def _days(n: int) -> str:
    return f"{n} day" if n == 1 else f"{n} days"


def _resolve_invite(
    db: Session,
    enrollment: CampaignLead,
    status: ConnectionStatus,
    now: datetime,
) -> str:
    """Folds one profile observation into the enrollment. Returns what changed:
    "accepted", "not_accepted", "expired" or "" (still waiting)."""
    invited_at = enrollment.invite_sent_at or now
    age = now - invited_at
    waited = tracking.days_between(invited_at, now) or 0
    enrollment.last_checked_at = now

    if status is ConnectionStatus.CONNECTED:
        enrollment.check_count += 1
        enrollment.accepted_at = enrollment.accepted_at or now
        enrollment.connection_state = ConnectionState.CONNECTED.value
        enrollment.connection_resolved_at = now
        enrollment.next_check_at = None
        tracking.log_event(
            enrollment,
            EventType.INVITE_ACCEPTED,
            f"Accepted after {_days(waited)}",
            at=now,
            meta={"days_waited": waited},
        )
        # A step gated on `if_accepted` may now be eligible, so wake the enrollment
        # now rather than at its next scheduled look.
        if not enrollment.state.is_terminal:
            enrollment.next_run_at = now
        return "accepted"

    if status is ConnectionStatus.UNKNOWN:
        # The page could not be read: say nothing about the invite, look again soon.
        enrollment.next_check_at = now + timedelta(hours=2)
        return ""

    enrollment.check_count += 1

    if status is ConnectionStatus.NOT_CONNECTED:
        if _previous_observation(db, enrollment.id) == ConnectionStatus.NOT_CONNECTED.value:
            enrollment.connection_state = ConnectionState.NOT_ACCEPTED.value
            enrollment.connection_resolved_at = now
            enrollment.next_check_at = None
            tracking.log_event(
                enrollment,
                EventType.INVITE_NOT_ACCEPTED,
                "No longer pending and not connected: declined, withdrawn or lapsed",
                at=now,
                meta={"days_waited": waited},
            )
            return "not_accepted"
        # One sighting is not proof; confirm on a quick second look.
        tracking.log_event(
            enrollment,
            EventType.INVITE_STILL_PENDING,
            "Not shown as pending; confirming on the next check",
            at=now,
            meta={"observed": ConnectionStatus.NOT_CONNECTED.value},
        )
        enrollment.next_check_at = now + timedelta(minutes=30)
        return ""

    # PENDING
    tracking.log_event(
        enrollment,
        EventType.INVITE_STILL_PENDING,
        f"Still pending after {_days(waited)}",
        at=now,
        meta={"observed": ConnectionStatus.PENDING.value, "days_waited": waited},
    )
    if age >= tracking.tracking_window():
        enrollment.connection_state = ConnectionState.EXPIRED.value
        enrollment.connection_resolved_at = now
        enrollment.next_check_at = None
        tracking.log_event(
            enrollment,
            EventType.INVITE_EXPIRED,
            f"No response after {_days(waited)}; no longer tracking",
            at=now,
            meta={"days_waited": waited},
        )
        return "expired"
    enrollment.next_check_at = now + tracking.next_check_delay(age)
    return ""


@celery_app.task(name="linkedin.sync.check_acceptances", bind=True, max_retries=0)
def check_acceptances(self: Any, account_id: str) -> dict[str, int]:
    """Tracks every pending invite: accepted, still pending, not accepted, or expired.

    Runs regardless of what the enrollment itself is doing: a campaign that ends
    right after the invite still needs its outcome recorded. Each look is a real
    page load, so a lead is only visited when its `next_check_at` is due, on a
    schedule that backs off (see `tracking.next_check_delay`).
    """
    _ = self
    now = datetime.now(UTC)
    counts = {"accepted": 0, "not_accepted": 0, "expired": 0, "checked": 0}

    with session_scope() as db:
        account = db.get(LinkedInAccount, account_id)
        if account is None or account.status is not LinkedInAccountStatus.ACTIVE:
            return counts
        if not account.is_connected:
            return counts

        pending = list(
            db.execute(
                select(CampaignLead, Lead)
                .join(Lead, Lead.id == CampaignLead.lead_id)
                .where(
                    CampaignLead.linkedin_account_id == account.id,
                    CampaignLead.connection_state == ConnectionState.PENDING.value,
                    CampaignLead.next_check_at.isnot(None),
                    CampaignLead.next_check_at <= now,
                )
                .order_by(CampaignLead.next_check_at)
                .limit(ACCEPTANCE_BATCH)
            ).all()
        )
        if not pending:
            return counts

        campaign_names = {
            c.id: c.name
            for c in db.execute(
                select(Campaign).where(Campaign.id.in_({e.campaign_id for e, _ in pending}))
            ).scalars()
        }
        unanswered: list[CampaignLead] = []

        try:
            with locks.account_slot(account.id):
                driver = build_driver(account)
                try:
                    for enrollment, lead in pending:
                        if not lead.public_id:
                            enrollment.next_check_at = None
                            continue
                        classification, status = driver.get_connection_status(lead.public_id)
                        counts["checked"] += 1

                        if not classification.ok:
                            outcome = health.apply_classification(account, classification, now=now)
                            enrollment.next_check_at = now + timedelta(hours=1)
                            if outcome.circuit_opened:
                                dispatcher.pause_account_work(db, account.id, outcome.detail)
                                break
                            continue

                        health.apply_classification(account, classification, now=now)
                        changed = _resolve_invite(db, enrollment, status, now)
                        db.flush()
                        if changed == "accepted":
                            counts["accepted"] += 1
                            who = lead.full_name or lead.public_id
                            notification_service.create_sync(
                                db,
                                account.workspace_id,
                                NotificationType.INVITE_UPDATE,
                                f"{who} accepted your connection request",
                                body=f"Campaign: {campaign_names.get(enrollment.campaign_id, '')}",
                                link=f"/campaigns/{enrollment.campaign_id}/tracking",
                            )
                        elif changed in ("not_accepted", "expired"):
                            counts[changed] += 1
                            unanswered.append(enrollment)
                finally:
                    driver.close()
        except locks.SlotBusy:
            return counts

        # One summary per run, not one bell per lead: twenty silent invites
        # should not bury the inbox notifications.
        for campaign_id in {e.campaign_id for e in unanswered}:
            n = sum(1 for e in unanswered if e.campaign_id == campaign_id)
            notification_service.create_sync(
                db,
                account.workspace_id,
                NotificationType.INVITE_UPDATE,
                f"{n} invite{'' if n == 1 else 's'} not accepted",
                body=f"Campaign: {campaign_names.get(campaign_id, '')}. See who in the tracker.",
                link=f"/campaigns/{campaign_id}/tracking",
            )

    if counts["accepted"] or counts["not_accepted"] or counts["expired"]:
        log.info("sync.invite_tracking", account_id=account_id, **counts)
    return counts


@celery_app.task(name="linkedin.sync.poll_all")
def poll_all() -> dict[str, int]:
    """Beat job: spread reply and acceptance polling across active accounts.

    Offsets are staggered: a thousand accounts calling LinkedIn in the same
    second is a pattern in itself, regardless of per-account pacing.
    """
    with session_scope() as db:
        account_ids = [
            str(account_id)
            for account_id in db.execute(
                select(LinkedInAccount.id).where(
                    LinkedInAccount.status == LinkedInAccountStatus.ACTIVE,
                    LinkedInAccount.session_ciphertext.isnot(None),
                )
            ).scalars()
        ]

    if not account_ids:
        return {"queued": 0}

    offsets = pacing.spread_start_times(len(account_ids), window_seconds=240)
    for account_id, offset in zip(account_ids, offsets, strict=True):
        poll_replies.apply_async(args=[account_id], countdown=offset, queue="linkedin.sync")
        check_acceptances.apply_async(
            args=[account_id], countdown=offset + 30, queue="linkedin.sync"
        )

    return {"queued": len(account_ids)}


def deliver_text(db: Session, conversation: Conversation, text: str, author: str) -> dict[str, Any]:
    """Sends `text` into this thread from its account and records it.

    The one write path for inbox messages, whether a person typed them or the
    assistant did; `author` is what later tells the two apart.
    """
    now = datetime.now(UTC)
    account = db.get(LinkedInAccount, conversation.linkedin_account_id)
    if account is None or not account.is_connected:
        return {"ok": False, "reason": "account not connected"}

    lead = db.get(Lead, conversation.lead_id) if conversation.lead_id else None
    # The browser driver opens /in/<id>/; the lead's own slug is the most
    # reliable id, the member id from the thread works too.
    target = (lead.public_id if lead and lead.public_id else "") or conversation.participant_urn

    try:
        with locks.account_slot(account.id):
            driver = build_driver(account)
            try:
                result = driver.send_message(target, text)
            finally:
                driver.close()
    except locks.SlotBusy:
        return {"ok": False, "reason": "account busy"}

    health.apply_classification(account, result.classification, now=now)
    if not result.classification.ok:
        log.warning("sync.send_reply_failed", conversation_id=str(conversation.id), author=author)
        return {"ok": False, "reason": result.classification.response_class.value}

    db.add(
        Message(
            workspace_id=conversation.workspace_id,
            conversation_id=conversation.id,
            # Only a real LinkedIn event id is stored; the poll adopts the id
            # when LinkedIn echoes this message back.
            remote_event_urn=result.remote_id if result.remote_id.startswith("urn:li:") else "",
            direction=MessageDirection.OUTBOUND,
            body=text,
            sent_at=now,
            author=author,
        )
    )
    conversation.last_message_at = now
    conversation.last_message_text = text
    conversation.last_message_from_me = True
    conversation.bot_draft = ""
    conversation.bot_draft_at = None
    account.next_allowed_at = pacing.next_allowed_at(now)
    return {"ok": True}


@celery_app.task(name="linkedin.action.send_reply", bind=True, max_retries=2)
def send_reply(self: Any, conversation_id: str, text: str, author: str = "human") -> dict[str, Any]:
    """Sends a reply from the inbox: one a person wrote, or an approved draft."""
    _ = self
    with session_scope() as db:
        conversation = db.get(Conversation, conversation_id)
        if conversation is None:
            return {"ok": False, "reason": "conversation not found"}
        return deliver_text(db, conversation, text, author)
