"""Named assistants: a campaign's leads are answered by the assistant that
campaign picked, in its voice, with its questions and its SOPs — never the
SOPs of another assistant. Claude is never called; `ai.decide` is replaced.
"""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient
from sqlalchemy.orm import Session

from app.ai import assistant as ai
from app.models.assistant import AssistantProfile, KnowledgeItem
from app.models.inbox import Conversation
from app.models.leads import Lead
from app.models.linkedin import LinkedInAccount
from app.models.tenancy import Workspace
from app.services.assistant_service import effective_settings, resolve_settings
from app.worker.tasks import assistant as bot
from tests.test_assistant import REPLY, scheduled, set_mode, thread  # noqa: F401
from tests.test_campaigns_api import auth, setup_workspace, step
from tests.test_inbox import _bind_session_scope, enroll, make_campaign


def _profile(db: Session, workspace_id: Any, name: str, **values: Any) -> AssistantProfile:
    profile = AssistantProfile(workspace_id=workspace_id, name=name, **values)
    db.add(profile)
    db.flush()
    return profile


def _from_campaign(
    db: Session, workspace: Workspace, convo: Conversation, profile: AssistantProfile | None
) -> None:
    """Puts the thread's lead in a campaign that picked `profile`."""
    account = db.get(LinkedInAccount, convo.linkedin_account_id)
    lead = db.get(Lead, convo.lead_id)
    assert account is not None and lead is not None
    campaign = make_campaign(db, workspace, account)
    if profile is not None:
        campaign.settings = {"assistant_id": str(profile.id)}
    enrollment = enroll(db, campaign, account, lead)
    convo.campaign_lead_id = enrollment.id
    db.flush()


def _capture(monkeypatch) -> list[tuple[ai.AssistantConfig, list[str]]]:
    seen: list[tuple[ai.AssistantConfig, list[str]]] = []

    def fake(config: ai.AssistantConfig, knowledge: list[ai.KnowledgeDoc], *_a: Any, **_k: Any) -> ai.BotDecision:
        seen.append((config, sorted(doc.title for doc in knowledge)))
        return REPLY

    monkeypatch.setattr(bot.ai, "decide", fake)
    return seen


def test_a_campaigns_assistant_answers_in_its_voice_from_its_sops(
    monkeypatch, sdb: Session, scheduled  # noqa: F811
) -> None:
    workspace, convo, _ = thread(sdb)
    set_mode(sdb, workspace, "draft", persona="Default voice", collect_fields=["email"])
    hr = _profile(
        sdb, workspace.id, "HR recruiter", persona="Priya, HR at Acme", collect_fields=["notice period"]
    )
    team = _profile(sdb, workspace.id, "Internal team", persona="A teammate")
    sdb.add_all(
        [
            KnowledgeItem(workspace_id=workspace.id, title="Company facts", content="shared"),
            KnowledgeItem(workspace_id=workspace.id, title="Job description", content="jd", assistant_ids=[hr.id]),
            KnowledgeItem(workspace_id=workspace.id, title="Team rota", content="rota", assistant_ids=[team.id]),
        ]
    )
    _from_campaign(sdb, workspace, convo, hr)
    seen = _capture(monkeypatch)

    with _bind_session_scope(monkeypatch, bot, sdb):
        bot.respond(str(convo.id))

    config, titles = seen[0]
    assert config.persona == "Priya, HR at Acme"
    assert config.collect_fields == ("notice period",)
    assert titles == ["Company facts", "Job description"]  # never the team's rota


def test_a_thread_from_no_campaign_uses_the_default_and_only_shared_sops(
    monkeypatch, sdb: Session, scheduled  # noqa: F811
) -> None:
    workspace, convo, _ = thread(sdb)
    set_mode(sdb, workspace, "draft", persona="Default voice")
    hr = _profile(sdb, workspace.id, "HR recruiter", persona="Priya")
    sdb.add_all(
        [
            KnowledgeItem(workspace_id=workspace.id, title="Company facts", content="shared"),
            KnowledgeItem(workspace_id=workspace.id, title="Job description", content="jd", assistant_ids=[hr.id]),
        ]
    )
    sdb.flush()
    seen = _capture(monkeypatch)

    with _bind_session_scope(monkeypatch, bot, sdb):
        bot.respond(str(convo.id))

    config, titles = seen[0]
    assert config.persona == "Default voice"
    assert titles == ["Company facts"]


def test_an_assistant_set_to_off_keeps_its_campaign_quiet(
    monkeypatch, sdb: Session, scheduled  # noqa: F811
) -> None:
    workspace, convo, _ = thread(sdb)
    set_mode(sdb, workspace, "auto")
    _from_campaign(sdb, workspace, convo, _profile(sdb, workspace.id, "Quiet", mode="off"))
    seen = _capture(monkeypatch)

    with _bind_session_scope(monkeypatch, bot, sdb):
        result = bot.respond(str(convo.id))

    assert result["reason"] == "assistant is off"
    assert seen == []


def test_an_assistant_is_never_louder_than_the_workspace() -> None:
    base = resolve_settings({"mode": "auto"})
    draft_only = AssistantProfile(name="HR", mode="draft", persona="", instructions="", handoff_topics="", collect_fields=[])
    assert effective_settings(base, draft_only)["mode"] == "draft"

    inherit = AssistantProfile(name="HR", mode="inherit", persona="", instructions="", handoff_topics="", collect_fields=[])
    assert effective_settings(base, inherit)["mode"] == "auto"
    assert effective_settings(resolve_settings({"mode": "off"}), inherit)["mode"] == "off"
    assert effective_settings(resolve_settings({"mode": "draft"}), inherit)["mode"] == "draft"


# ── API ──────────────────────────────────────────────────────────────────────


async def test_assistants_crud_and_campaigns_pick_one(client: AsyncClient, db: Any) -> None:
    token, ws, account_id = await setup_workspace(client, db)
    base = f"/api/v1/workspaces/{ws}/assistant"

    hr = await client.post(
        f"{base}/profiles",
        json={"name": "HR recruiter", "persona": "Priya", "collect_fields": ["notice period", "notice period"]},
        headers=auth(token),
    )
    assert hr.status_code == 201, hr.text
    hr_id = hr.json()["id"]
    assert hr.json()["mode"] == "inherit"
    assert hr.json()["collect_fields"] == ["notice period"]

    renamed = await client.patch(
        f"{base}/profiles/{hr_id}", json={"name": "Hiring", "mode": "draft"}, headers=auth(token)
    )
    assert renamed.json()["name"] == "Hiring" and renamed.json()["mode"] == "draft"

    sop = await client.post(
        f"{base}/knowledge",
        json={"title": "JD", "content": "Backend role", "assistant_ids": [hr_id]},
        headers=auth(token),
    )
    assert sop.status_code == 201 and sop.json()["assistant_ids"] == [hr_id]

    created = await client.post(
        f"/api/v1/workspaces/{ws}/campaigns",
        json={
            "name": "Backend hiring",
            "linkedin_account_id": account_id,
            "steps": [step("invite")],
            "assistant_id": hr_id,
            "ai_brief": "Hiring backend engineers",
        },
        headers=auth(token),
    )
    assert created.status_code == 201, created.text
    campaign = created.json()
    assert campaign["assistant_id"] == hr_id and campaign["assistant_name"] == "Hiring"
    assert campaign["ai_brief"] == "Hiring backend engineers"

    # Back to the default assistant.
    cleared = await client.patch(
        f"/api/v1/workspaces/{ws}/campaigns/{campaign['id']}",
        json={"assistant_id": None},
        headers=auth(token),
    )
    assert cleared.json()["assistant_id"] is None
    assert cleared.json()["assistant_name"] == "Default assistant"

    # Leaving it out of a patch keeps whatever is set.
    await client.patch(
        f"/api/v1/workspaces/{ws}/campaigns/{campaign['id']}",
        json={"assistant_id": hr_id},
        headers=auth(token),
    )
    kept = await client.patch(
        f"/api/v1/workspaces/{ws}/campaigns/{campaign['id']}",
        json={"ai_brief": "changed"},
        headers=auth(token),
    )
    assert kept.json()["assistant_id"] == hr_id

    # Deleting it: the campaign falls back to the default, and the SOP only it
    # read is switched off rather than becoming shared by every assistant.
    gone = await client.delete(f"{base}/profiles/{hr_id}", headers=auth(token))
    assert gone.status_code == 204
    after = await client.get(f"/api/v1/workspaces/{ws}/campaigns/{campaign['id']}", headers=auth(token))
    assert after.json()["assistant_id"] is None
    sops = (await client.get(f"{base}/knowledge", headers=auth(token))).json()
    assert sops[0]["assistant_ids"] == [] and sops[0]["enabled"] is False


async def test_a_campaign_cannot_pick_a_made_up_assistant(client: AsyncClient, db: Any) -> None:
    import uuid

    token, ws, account_id = await setup_workspace(client, db)
    response = await client.post(
        f"/api/v1/workspaces/{ws}/campaigns",
        json={
            "name": "x",
            "linkedin_account_id": account_id,
            "steps": [step("invite")],
            "assistant_id": str(uuid.uuid4()),
        },
        headers=auth(token),
    )
    assert response.status_code == 404
    listed = await client.get(f"/api/v1/workspaces/{ws}/campaigns", headers=auth(token))
    assert listed.json() == []  # refused before anything was created
