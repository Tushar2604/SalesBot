"""The inbox assistant: when it speaks, when it stays quiet, and how a person
takes over. Claude is never called here — `ai.decide` is replaced with canned
decisions, because what matters is the gating around it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import assistant as ai
from app.linkedin.driver import MessageEvent
from app.models.campaigns import ActionTask, StepType, TaskStatus
from app.models.inbox import Conversation, Message, MessageAuthor, MessageDirection
from app.models.tenancy import Workspace
from app.services.assistant_service import resolve_settings
from app.worker.tasks import assistant as bot
from app.worker.tasks import sync as sync_tasks
from tests.test_inbox import (
    START,
    _bind_session_scope,
    make_account,
    make_lead,
    make_workspace,
    snapshot,
)


def set_mode(db: Session, workspace: Workspace, mode: str, **extra: Any) -> None:
    workspace.settings = {"assistant": {"mode": mode, "working_hours_only": False, **extra}}
    db.flush()


def thread(db: Session, *, inbound_last: bool = True) -> tuple[Workspace, Conversation, Message]:
    workspace = make_workspace(db)
    account = make_account(db, workspace)
    lead = make_lead(db, workspace, public_id="ravi-k")
    convo = Conversation(
        workspace_id=workspace.id,
        linkedin_account_id=account.id,
        lead_id=lead.id,
        conversation_urn="thread-1",
        participant_urn="ACoAAravi",
        participant_name="Ravi K",
    )
    db.add(convo)
    db.flush()
    now = datetime.now(UTC)
    db.add(
        Message(
            workspace_id=workspace.id,
            conversation_id=convo.id,
            direction=MessageDirection.OUTBOUND,
            body="Hi Ravi, we're hiring backend engineers.",
            sent_at=now - timedelta(minutes=30),
            author=MessageAuthor.CAMPAIGN.value,
        )
    )
    last = Message(
        workspace_id=workspace.id,
        conversation_id=convo.id,
        direction=MessageDirection.INBOUND if inbound_last else MessageDirection.OUTBOUND,
        body="Can you share the JD? You can reach me at ravi@example.com",
        sent_at=now - timedelta(minutes=5),
    )
    db.add(last)
    db.flush()
    return workspace, convo, last


@pytest.fixture
def scheduled(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Captures apply_async calls instead of queueing them."""
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(bot.respond, "apply_async", lambda **kw: calls.append(("respond", kw)))
    monkeypatch.setattr(bot.send, "apply_async", lambda **kw: calls.append(("send", kw)))
    return calls


def decide_returns(monkeypatch: pytest.MonkeyPatch, decision: ai.BotDecision | None) -> list[int]:
    calls: list[int] = []

    def fake(*_a: Any, **_k: Any) -> ai.BotDecision | None:
        calls.append(1)
        return decision

    monkeypatch.setattr(bot.ai, "decide", fake)
    return calls


REPLY = ai.BotDecision(
    action="reply",
    reply="Sure! Backend engineer: Python, 3+ years, remote.",
    handoff_reason="",
    shared_facts=[ai.SharedFact(field="email", value="ravi@example.com")],
)


# ── settings ─────────────────────────────────────────────────────────────────


def test_settings_default_to_off_and_clamp_to_safe_ranges() -> None:
    assert resolve_settings(None)["mode"] == "off"
    cfg = resolve_settings(
        {
            "mode": "rogue",
            "max_replies_per_thread_per_day": 999,
            "reply_delay_min_minutes": 30,
            "reply_delay_max_minutes": 5,
        }
    )
    assert cfg["mode"] == "off"
    assert cfg["max_replies_per_thread_per_day"] == 20
    assert cfg["reply_delay_max_minutes"] >= cfg["reply_delay_min_minutes"]


# ── respond: the gates ───────────────────────────────────────────────────────


def test_off_mode_never_calls_claude(monkeypatch, sdb: Session, scheduled) -> None:
    workspace, convo, _ = thread(sdb)
    set_mode(sdb, workspace, "off")
    calls = decide_returns(monkeypatch, REPLY)
    with _bind_session_scope(monkeypatch, bot, sdb):
        result = bot.respond(str(convo.id))
    assert result["reason"] == "assistant is off"
    assert calls == [] and scheduled == []


def test_paused_thread_is_left_alone(monkeypatch, sdb: Session, scheduled) -> None:
    workspace, convo, _ = thread(sdb)
    set_mode(sdb, workspace, "auto")
    convo.bot_paused = True
    calls = decide_returns(monkeypatch, REPLY)
    with _bind_session_scope(monkeypatch, bot, sdb):
        bot.respond(str(convo.id))
    assert calls == [] and scheduled == []


def test_a_person_typing_defers_the_bot(monkeypatch, sdb: Session, scheduled) -> None:
    workspace, convo, _ = thread(sdb)
    set_mode(sdb, workspace, "auto")
    convo.human_active_until = datetime.now(UTC) + timedelta(seconds=60)
    calls = decide_returns(monkeypatch, REPLY)
    with _bind_session_scope(monkeypatch, bot, sdb):
        result = bot.respond(str(convo.id))
    assert result["reason"] == "a person is typing"
    assert calls == []
    assert [name for name, _ in scheduled] == ["respond"]  # tries again after they stop


def test_nothing_to_answer_when_we_spoke_last(monkeypatch, sdb: Session, scheduled) -> None:
    workspace, convo, _ = thread(sdb, inbound_last=False)
    set_mode(sdb, workspace, "auto")
    calls = decide_returns(monkeypatch, REPLY)
    with _bind_session_scope(monkeypatch, bot, sdb):
        bot.respond(str(convo.id))
    assert calls == []


# ── respond: outcomes ────────────────────────────────────────────────────────


def test_draft_mode_saves_a_draft_and_the_shared_email(
    monkeypatch, sdb: Session, scheduled
) -> None:
    workspace, convo, _ = thread(sdb)
    set_mode(sdb, workspace, "draft")
    decide_returns(monkeypatch, REPLY)
    with _bind_session_scope(monkeypatch, bot, sdb):
        result = bot.respond(str(convo.id))
    assert result["action"] == "draft"
    assert scheduled == []  # nothing is sent in draft mode
    sdb.refresh(convo)
    assert convo.bot_draft == REPLY.reply
    assert convo.bot_extracted == {"email": "ravi@example.com"}
    from app.models.leads import Lead

    lead = sdb.get(Lead, convo.lead_id)
    assert lead is not None and lead.email == "ravi@example.com"


def test_auto_mode_schedules_the_send_after_a_pause(monkeypatch, sdb: Session, scheduled) -> None:
    workspace, convo, last = thread(sdb)
    set_mode(sdb, workspace, "auto", reply_delay_min_minutes=2, reply_delay_max_minutes=3)
    decide_returns(monkeypatch, REPLY)
    before = datetime.now(UTC)
    with _bind_session_scope(monkeypatch, bot, sdb):
        bot.respond(str(convo.id))
    assert [name for name, _ in scheduled] == ["send"]
    kw = scheduled[0][1]
    assert kw["args"] == [str(convo.id), REPLY.reply, str(last.id)]
    assert before + timedelta(minutes=2) <= kw["eta"] <= before + timedelta(minutes=3, seconds=5)


def test_handoff_pauses_the_thread_with_the_reason(monkeypatch, sdb: Session, scheduled) -> None:
    workspace, convo, _ = thread(sdb)
    set_mode(sdb, workspace, "auto")
    decide_returns(
        monkeypatch,
        ai.BotDecision(
            action="handoff", reply="", handoff_reason="Asked about salary", shared_facts=[]
        ),
    )
    with _bind_session_scope(monkeypatch, bot, sdb):
        bot.respond(str(convo.id))
    sdb.refresh(convo)
    assert convo.bot_paused is True
    assert "salary" in convo.bot_pause_reason
    assert scheduled == []


def test_thread_reply_limit_pauses_instead_of_replying(
    monkeypatch, sdb: Session, scheduled
) -> None:
    workspace, convo, _ = thread(sdb)
    set_mode(sdb, workspace, "auto", max_replies_per_thread_per_day=1)
    sdb.add(
        Message(
            workspace_id=workspace.id,
            conversation_id=convo.id,
            direction=MessageDirection.OUTBOUND,
            body="earlier bot reply",
            sent_at=datetime.now(UTC) - timedelta(hours=1),
            author=MessageAuthor.BOT.value,
        )
    )
    sdb.flush()
    calls = decide_returns(monkeypatch, REPLY)
    with _bind_session_scope(monkeypatch, bot, sdb):
        bot.respond(str(convo.id))
    assert calls == []
    sdb.refresh(convo)
    assert convo.bot_paused is True


# ── send: last-moment checks ─────────────────────────────────────────────────


def _capture_delivery(monkeypatch) -> list[tuple[str, str]]:
    sent: list[tuple[str, str]] = []

    def fake(db, conversation, text, author):
        sent.append((text, author))
        return {"ok": True}

    monkeypatch.setattr(bot, "deliver_text", fake)
    return sent


def test_send_delivers_as_the_bot(monkeypatch, sdb: Session, scheduled) -> None:
    workspace, convo, last = thread(sdb)
    set_mode(sdb, workspace, "auto")
    convo.bot_draft = REPLY.reply
    sent = _capture_delivery(monkeypatch)
    with _bind_session_scope(monkeypatch, bot, sdb):
        bot.send(str(convo.id), REPLY.reply, str(last.id))
    assert sent == [(REPLY.reply, "bot")]


def test_send_is_dropped_when_the_prospect_wrote_again(
    monkeypatch, sdb: Session, scheduled
) -> None:
    workspace, convo, last = thread(sdb)
    set_mode(sdb, workspace, "auto")
    convo.bot_draft = REPLY.reply
    sdb.add(
        Message(
            workspace_id=workspace.id,
            conversation_id=convo.id,
            direction=MessageDirection.INBOUND,
            body="Also, is it remote?",
            sent_at=datetime.now(UTC),
        )
    )
    sdb.flush()
    sent = _capture_delivery(monkeypatch)
    with _bind_session_scope(monkeypatch, bot, sdb):
        result = bot.send(str(convo.id), REPLY.reply, str(last.id))
    assert sent == [] and result["reason"] == "superseded by a newer message"


def test_send_is_dropped_when_a_person_took_over(monkeypatch, sdb: Session, scheduled) -> None:
    workspace, convo, last = thread(sdb)
    set_mode(sdb, workspace, "auto")
    convo.bot_draft = REPLY.reply
    convo.bot_paused = True
    convo.bot_pause_reason = "You replied yourself"
    sent = _capture_delivery(monkeypatch)
    with _bind_session_scope(monkeypatch, bot, sdb):
        bot.send(str(convo.id), REPLY.reply, str(last.id))
    assert sent == []


def test_send_waits_while_someone_is_typing(monkeypatch, sdb: Session, scheduled) -> None:
    workspace, convo, last = thread(sdb)
    set_mode(sdb, workspace, "auto")
    convo.bot_draft = REPLY.reply
    convo.human_active_until = datetime.now(UTC) + timedelta(seconds=45)
    sent = _capture_delivery(monkeypatch)
    with _bind_session_scope(monkeypatch, bot, sdb):
        bot.send(str(convo.id), REPLY.reply, str(last.id))
    assert sent == []
    assert [name for name, _ in scheduled] == ["send"]


def test_send_respects_an_edited_or_discarded_draft(monkeypatch, sdb: Session, scheduled) -> None:
    workspace, convo, last = thread(sdb)
    set_mode(sdb, workspace, "auto")
    convo.bot_draft = ""  # discarded in the inbox
    sent = _capture_delivery(monkeypatch)
    with _bind_session_scope(monkeypatch, bot, sdb):
        bot.send(str(convo.id), REPLY.reply, str(last.id))
    assert sent == []


# ── takeover detection during inbox sync ─────────────────────────────────────


def _event(urn: str, text: str, *, from_me: bool, minutes: int) -> MessageEvent:
    return MessageEvent(
        event_urn=urn, from_me=from_me, text=text, sent_at=START + timedelta(minutes=minutes)
    )


def test_a_message_typed_on_linkedin_itself_pauses_the_bot(sdb: Session) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    first = snapshot(events=[_event("e1", "Hi, can you share the JD?", from_me=False, minutes=0)])
    sync_tasks._ingest_conversation(sdb, account, first, None, None, START)

    later = snapshot(
        events=[
            _event("e2", "Let me call you instead", from_me=True, minutes=5),
            _event("e1", "Hi, can you share the JD?", from_me=False, minutes=0),
        ]
    )
    sync_tasks._ingest_conversation(sdb, account, later, None, None, START)

    convo = sdb.execute(select(Conversation)).scalar_one()
    assert convo.bot_paused is True
    assert "LinkedIn directly" in convo.bot_pause_reason


def test_old_history_on_a_new_thread_does_not_pause_the_bot(sdb: Session) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    snap = snapshot(
        events=[
            _event("e2", "Thanks!", from_me=False, minutes=5),
            _event("e1", "Hello from months ago", from_me=True, minutes=0),
        ]
    )
    sync_tasks._ingest_conversation(sdb, account, snap, None, None, START)
    assert sdb.execute(select(Conversation)).scalar_one().bot_paused is False


def test_the_bots_own_message_is_adopted_not_mistaken_for_a_person(sdb: Session) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    sync_tasks._ingest_conversation(
        sdb,
        account,
        snapshot(events=[_event("e1", "JD please", from_me=False, minutes=0)]),
        None,
        None,
        START,
    )
    convo = sdb.execute(select(Conversation)).scalar_one()
    sdb.add(
        Message(
            workspace_id=workspace.id,
            conversation_id=convo.id,
            direction=MessageDirection.OUTBOUND,
            body="Sure, here it is:  Python,\n3+ years",
            sent_at=START + timedelta(minutes=3),
            author=MessageAuthor.BOT.value,
        )
    )
    sdb.flush()

    echoed = snapshot(
        events=[
            _event("e2", "Sure, here it is: Python, 3+ years", from_me=True, minutes=3),
            _event("e1", "JD please", from_me=False, minutes=0),
        ]
    )
    inserted = sync_tasks._ingest_conversation(sdb, account, echoed, None, None, START)

    assert inserted == []
    sdb.refresh(convo)
    assert convo.bot_paused is False
    outbound = (
        sdb.execute(select(Message).where(Message.direction == MessageDirection.OUTBOUND))
        .scalars()
        .all()
    )
    assert len(outbound) == 1 and outbound[0].remote_event_urn == "e2"


def test_a_campaign_message_is_recognised_not_mistaken_for_a_person(sdb: Session) -> None:
    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    sync_tasks._ingest_conversation(
        sdb,
        account,
        snapshot(events=[_event("e1", "Hi", from_me=False, minutes=0)]),
        None,
        None,
        START,
    )
    sdb.add(
        ActionTask(
            workspace_id=workspace.id,
            linkedin_account_id=account.id,
            action_type=StepType.MESSAGE,
            payload={"body": "Thanks for connecting, Ravi!"},
            scheduled_at=START,
            status=TaskStatus.SUCCEEDED,
            finished_at=START,
            idempotency_key="k-1",
        )
    )
    sdb.flush()
    snap = snapshot(
        events=[
            _event("e2", "Thanks for connecting, Ravi!", from_me=True, minutes=2),
            _event("e1", "Hi", from_me=False, minutes=0),
        ]
    )
    sync_tasks._ingest_conversation(sdb, account, snap, None, None, START)

    convo = sdb.execute(select(Conversation)).scalar_one()
    assert convo.bot_paused is False
    msg = sdb.execute(select(Message).where(Message.remote_event_urn == "e2")).scalar_one()
    assert msg.author == "campaign"


# ── provider chain: OpenAI first, Gemini as the fallback ─────────────────────


def _chain(monkeypatch, behaviours: dict[str, Any], order: str = "openai,gemini") -> list[str]:
    """Replaces the provider calls; returns the order they were tried in."""
    tried: list[str] = []
    monkeypatch.setattr(ai.settings, "ai_assistant_providers", order)

    def make(name: str):
        def call(system: str, user: str, client: Any):
            tried.append(name)
            outcome = behaviours[name]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        return call

    monkeypatch.setattr(ai, "_CALLS", {name: make(name) for name in behaviours})
    return tried


TURNS = [ai.Turn(True, "We're hiring"), ai.Turn(False, "Can you share the JD?")]
CFG = ai.AssistantConfig("HR", "", "")


def test_openai_answers_first(monkeypatch) -> None:
    tried = _chain(monkeypatch, {"openai": REPLY, "gemini": REPLY})
    assert (
        ai.decide(CFG, [], TURNS, "Ravi", clients={"openai": object(), "gemini": object()}) == REPLY
    )
    assert tried == ["openai"]


def test_gemini_takes_over_when_openai_fails(monkeypatch) -> None:
    tried = _chain(monkeypatch, {"openai": RuntimeError("503"), "gemini": REPLY})
    assert (
        ai.decide(CFG, [], TURNS, "Ravi", clients={"openai": object(), "gemini": object()}) == REPLY
    )
    assert tried == ["openai", "gemini"]


def test_gemini_takes_over_when_openai_output_is_unusable(monkeypatch) -> None:
    empty = ai.BotDecision(action="reply", reply="  ", handoff_reason="", shared_facts=[])
    tried = _chain(monkeypatch, {"openai": empty, "gemini": REPLY})
    assert (
        ai.decide(CFG, [], TURNS, "Ravi", clients={"openai": object(), "gemini": object()}) == REPLY
    )
    assert tried == ["openai", "gemini"]


def test_a_provider_without_a_key_is_skipped(monkeypatch) -> None:
    tried = _chain(monkeypatch, {"openai": REPLY, "gemini": REPLY})
    assert ai.decide(CFG, [], TURNS, "Ravi", clients={"gemini": object()}) == REPLY
    assert tried == ["gemini"]


def test_every_provider_declining_hands_off_to_a_person(monkeypatch) -> None:
    _chain(monkeypatch, {"openai": ai._Refused("x"), "gemini": ai._Refused("y")})
    decision = ai.decide(CFG, [], TURNS, "Ravi", clients={"openai": object(), "gemini": object()})
    assert decision is not None and decision.action == "handoff"


def test_all_failing_means_silence(monkeypatch) -> None:
    _chain(monkeypatch, {"openai": RuntimeError("a"), "gemini": RuntimeError("b")})
    assert (
        ai.decide(CFG, [], TURNS, "Ravi", clients={"openai": object(), "gemini": object()}) is None
    )


def test_provider_order_is_configurable(monkeypatch) -> None:
    tried = _chain(
        monkeypatch, {"openai": RuntimeError("x"), "gemini": REPLY}, order="gemini,openai"
    )
    ai.decide(CFG, [], TURNS, "Ravi", clients={"openai": object(), "gemini": object()})
    assert tried == ["gemini"]
