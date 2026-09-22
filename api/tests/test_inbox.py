"""Inbox ingestion, idempotency, AI classification, and the reply-stop
regression guard — service/engine level, against a real database.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.linkedin import fingerprint as fp_mod
from app.linkedin.classify import Classification, ResponseClass
from app.linkedin.driver import ConversationSnapshot, MessageEvent
from app.models.campaigns import Campaign, CampaignLead, CampaignStatus, EnrollmentState
from app.models.inbox import Conversation, ConversationLabel, LabelSource, Message, MessageDirection
from app.models.leads import Lead
from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus
from app.models.tenancy import Workspace
from app.worker.tasks import ai as ai_tasks
from app.worker.tasks import sync as sync_tasks
from app.linkedin import caps as caps_mod

START = datetime(2026, 9, 15, 9, 30, tzinfo=UTC)


# ── fixtures built directly, mirroring test_dispatcher.py's style ───────────


def make_workspace(db: Session) -> Workspace:
    workspace = Workspace(name="Acme", slug=f"acme-{uuid.uuid4().hex[:8]}")
    db.add(workspace)
    db.flush()
    return workspace


def make_account(db: Session, workspace: Workspace) -> LinkedInAccount:
    account = LinkedInAccount(
        workspace_id=workspace.id,
        label="Sender",
        status=LinkedInAccountStatus.ACTIVE,
        session_ciphertext=b"ciphertext",
        fingerprint=fp_mod.generate(),
        caps=caps_mod.default_caps(),
        timezone="UTC",
        proxy=None,
    )
    db.add(account)
    db.flush()
    return account


def make_lead(db: Session, workspace: Workspace, *, urn: str = "", public_id: str = "") -> Lead:
    lead = Lead(
        workspace_id=workspace.id,
        public_id=public_id or f"lead-{uuid.uuid4().hex[:12]}",
        linkedin_urn=urn,
        first_name="Test",
        last_name="Lead",
    )
    db.add(lead)
    db.flush()
    return lead


def make_campaign(
    db: Session, workspace: Workspace, account: LinkedInAccount, *, stop_on_reply: bool = True
) -> Campaign:
    campaign = Campaign(
        workspace_id=workspace.id,
        linkedin_account_id=account.id,
        name="Test campaign",
        status=CampaignStatus.RUNNING,
        stop_on_reply=stop_on_reply,
        started_at=START,
    )
    db.add(campaign)
    db.flush()
    return campaign


def enroll(db: Session, campaign: Campaign, account: LinkedInAccount, lead: Lead) -> CampaignLead:
    enrollment = CampaignLead(
        workspace_id=campaign.workspace_id,
        campaign_id=campaign.id,
        lead_id=lead.id,
        linkedin_account_id=account.id,
        state=EnrollmentState.PENDING,
        next_run_at=START,
    )
    db.add(enrollment)
    db.flush()
    return enrollment


def snapshot(
    *,
    urn: str = "urn:li:fsd_conversation:abc",
    participant_urn: str = "urn:li:fsd_profile:lead1",
    from_me: bool = False,
    text: str = "Sounds interesting, tell me more",
    events: list[MessageEvent] | None = None,
) -> ConversationSnapshot:
    when = START
    return ConversationSnapshot(
        conversation_urn=urn,
        participant_urn=participant_urn,
        participant_name="Lead One",
        last_activity_at=when,
        last_message_text=text,
        last_message_from_me=from_me,
        unread=not from_me,
        events=events
        if events is not None
        else [MessageEvent(event_urn="evt-1", from_me=from_me, text=text, sent_at=when)],
    )


@contextmanager
def _bind_session_scope(monkeypatch, module, db: Session) -> Iterator[None]:
    """Points a task module's `session_scope()` at the test's transactional db.

    Commits land on the fixture's SAVEPOINT (see conftest's `sdb`), so the
    rollback at test teardown still wins.
    """

    @contextmanager
    def _scope() -> Iterator[Session]:
        yield db
        db.commit()

    monkeypatch.setattr(module, "session_scope", _scope)
    yield


# ── _leads_by_profile / _ingest_conversation ─────────────────────────────────


def test_leads_by_profile_matches_urn_and_public_id(sdb: Session) -> None:
    workspace = make_workspace(sdb)
    lead = make_lead(sdb, workspace, urn="urn:li:fsd_profile:abc123", public_id="jane-doe")

    index = sync_tasks._leads_by_profile(sdb, workspace.id)

    assert index["abc123"].id == lead.id
    assert index["jane-doe"].id == lead.id


def test_ingest_conversation_creates_thread_and_message(sdb: Session) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    lead = make_lead(sdb, workspace, urn="urn:li:fsd_profile:lead1")

    inserted = sync_tasks._ingest_conversation(sdb, account, snapshot(), lead, None, START)

    assert len(inserted) == 1
    assert inserted[0].direction is MessageDirection.INBOUND

    conversation = sdb.execute(select(Conversation)).scalar_one()
    assert conversation.lead_id == lead.id
    assert conversation.last_message_text == "Sounds interesting, tell me more"
    assert conversation.last_message_from_me is False


def test_ingest_conversation_is_idempotent(sdb: Session) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    snap = snapshot()

    first = sync_tasks._ingest_conversation(sdb, account, snap, None, None, START)
    second = sync_tasks._ingest_conversation(sdb, account, snap, None, None, START)

    assert len(first) == 1
    assert len(second) == 0  # same event id, not re-inserted
    assert sdb.execute(select(Message)).scalars().all().__len__() == 1

    conversations = sdb.execute(select(Conversation)).scalars().all()
    assert len(conversations) == 1  # updated in place, not duplicated


def test_ingest_conversation_dedupes_without_event_id(sdb: Session) -> None:
    """LinkedIn doesn't always give an event id; fall back to timestamp+body."""
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    snap = snapshot(events=[MessageEvent(event_urn="", from_me=False, text="hi", sent_at=START)])

    sync_tasks._ingest_conversation(sdb, account, snap, None, None, START)
    second = sync_tasks._ingest_conversation(sdb, account, snap, None, None, START)

    assert len(second) == 0
    assert sdb.execute(select(Message)).scalars().all().__len__() == 1


# ── poll_replies: persistence + the existing reply-stop behaviour ───────────


def test_poll_replies_persists_and_stops_sequence(monkeypatch, sdb: Session) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    lead = make_lead(sdb, workspace, urn="urn:li:fsd_profile:lead1")
    campaign = make_campaign(sdb, workspace, account, stop_on_reply=True)
    enrollment = enroll(sdb, campaign, account, lead)
    sdb.commit()

    class FakeDriver:
        def list_conversations(self, limit: int = 20):
            return Classification(ResponseClass.OK), [
                snapshot(participant_urn="urn:li:fsd_profile:lead1")
            ]

        def close(self) -> None:
            pass

    @contextmanager
    def _no_lock(account_id, *, ttl=None):
        yield

    sent_tasks: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(sync_tasks, "build_driver", lambda account: FakeDriver())
    monkeypatch.setattr(sync_tasks.locks, "account_slot", _no_lock)
    monkeypatch.setattr(
        sync_tasks.celery_app,
        "send_task",
        lambda name, args=(), **kw: sent_tasks.append((name, list(args))),
    )

    with _bind_session_scope(monkeypatch, sync_tasks, sdb):
        result = sync_tasks.poll_replies(str(account.id))

    assert result["stopped"] == 1

    sdb.refresh(enrollment)
    assert enrollment.state is EnrollmentState.REPLIED
    assert enrollment.replied_at is not None
    assert enrollment.next_run_at is None

    conversation = sdb.execute(select(Conversation)).scalar_one()
    assert conversation.lead_id == lead.id
    assert conversation.campaign_lead_id == enrollment.id

    messages = sdb.execute(select(Message)).scalars().all()
    assert len(messages) == 1
    assert messages[0].direction is MessageDirection.INBOUND

    # A new inbound message dispatches classification and wakes the assistant.
    assert sent_tasks == [
        ("ai.classify_message", [str(messages[0].id)]),
        ("assistant.respond", [str(conversation.id)]),
    ]


# ── ai.classify_message: label precedence ────────────────────────────────────


def test_classify_message_sets_label_when_unset(monkeypatch, sdb: Session) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    conversation = Conversation(
        workspace_id=workspace.id,
        linkedin_account_id=account.id,
        conversation_urn="urn:li:fsd_conversation:x",
    )
    sdb.add(conversation)
    sdb.flush()
    message = Message(
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        direction=MessageDirection.INBOUND,
        body="Not interested right now",
        sent_at=START,
    )
    sdb.add(message)
    sdb.commit()

    monkeypatch.setattr(ai_tasks, "classify_inbound", lambda text: ConversationLabel.NOT_INTERESTED)

    with _bind_session_scope(monkeypatch, ai_tasks, sdb):
        ai_tasks.classify_message(str(message.id))

    sdb.refresh(message)
    sdb.refresh(conversation)
    assert message.ai_label is ConversationLabel.NOT_INTERESTED
    assert conversation.label is ConversationLabel.NOT_INTERESTED
    assert conversation.label_source is LabelSource.AI


def test_classify_message_never_overwrites_a_manual_label(monkeypatch, sdb: Session) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    conversation = Conversation(
        workspace_id=workspace.id,
        linkedin_account_id=account.id,
        conversation_urn="urn:li:fsd_conversation:y",
        label=ConversationLabel.INTERESTED,
        label_source=LabelSource.MANUAL,
    )
    sdb.add(conversation)
    sdb.flush()
    message = Message(
        workspace_id=workspace.id,
        conversation_id=conversation.id,
        direction=MessageDirection.INBOUND,
        body="Actually never mind",
        sent_at=START,
    )
    sdb.add(message)
    sdb.commit()

    monkeypatch.setattr(ai_tasks, "classify_inbound", lambda text: ConversationLabel.NOT_INTERESTED)

    with _bind_session_scope(monkeypatch, ai_tasks, sdb):
        ai_tasks.classify_message(str(message.id))

    sdb.refresh(conversation)
    assert conversation.label is ConversationLabel.INTERESTED
    assert conversation.label_source is LabelSource.MANUAL
