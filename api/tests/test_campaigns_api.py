"""Campaign endpoints: validation, enrollment, launch preconditions.

The validation tests are the point. A campaign is aimed at a real LinkedIn
account, so a sequence that cannot work should be refused while it is still a
draft — not discovered when the first message bounces.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from app.linkedin import fingerprint as fp_mod


@pytest.fixture
def sent_tasks(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    def fake_send_task(name: str, *args: Any, **kwargs: Any) -> object:
        captured.append({"name": name, "args": kwargs.get("args") or []})

        class _Result:
            id = "stubbed"

        return _Result()

    from app.worker import celery_app as celery_module

    monkeypatch.setattr(celery_module.celery_app, "send_task", fake_send_task)
    return captured


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def setup_workspace(client: AsyncClient, db: Any) -> tuple[str, str, str]:
    """Returns (token, workspace_id, active_linkedin_account_id).

    The account is marked ACTIVE directly: connecting one for real would need
    LinkedIn, and these tests are about campaign rules.
    """
    signup = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": "owner@example.com",
            "password": "correct horse 7",
            "full_name": "Owner",
            "workspace_name": "Acme",
        },
    )
    token = signup.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers=auth(token))
    workspace_id = me.json()["workspaces"][0]["workspace"]["id"]

    from app.linkedin import caps as caps_mod
    from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus

    account = LinkedInAccount(
        workspace_id=workspace_id,
        label="Sender",
        status=LinkedInAccountStatus.ACTIVE,
        session_ciphertext=b"ciphertext",
        fingerprint=fp_mod.generate(),
        caps=caps_mod.default_caps(),
        timezone="UTC",
        proxy=None,
    )
    db.add(account)
    await db.flush()
    return token, workspace_id, str(account.id)


async def import_leads(client: AsyncClient, token: str, ws: str, count: int = 3) -> str:
    rows = ["Name,LinkedIn Profile,Company Name"]
    rows += [f"Lead {i},https://www.linkedin.com/in/lead-{i}-demo,Northwind" for i in range(count)]
    body = ("\n".join(rows) + "\n").encode()

    response = await client.post(
        f"/api/v1/workspaces/{ws}/leads/import-csv",
        headers=auth(token),
        files={"file": ("leads.csv", body, "text/csv")},
        data={"list_name": "Demo"},
    )
    assert response.status_code == 201, response.text
    return str(response.json()["list_id"])


def step(step_type: str, **overrides: Any) -> dict[str, Any]:
    return {
        "step_type": step_type,
        "delay_hours": 0,
        "only_if": "always",
        "on_condition_fail": "skip",
        "template": "",
        **overrides,
    }


# ── validation ───────────────────────────────────────────────────────────────


async def test_a_message_before_an_invite_is_refused(client: AsyncClient, db: Any) -> None:
    token, ws, account_id = await setup_workspace(client, db)

    response = await client.post(
        f"/api/v1/workspaces/{ws}/campaigns",
        json={
            "name": "Wrong order",
            "linkedin_account_id": account_id,
            "stop_on_reply": True,
            "steps": [
                step("message", template="Hi {{first_name|there}}"),
                step("invite"),
            ],
        },
        headers=auth(token),
    )

    assert response.status_code == 422
    problems = response.json()["error"]["details"]["problems"]
    assert any("before the connection request" in problem for problem in problems)


async def test_a_message_straight_after_an_invite_must_be_gated(
    client: AsyncClient, db: Any
) -> None:
    """Otherwise it is attempted on everyone who never connected."""
    token, ws, account_id = await setup_workspace(client, db)

    response = await client.post(
        f"/api/v1/workspaces/{ws}/campaigns",
        json={
            "name": "Ungated",
            "linkedin_account_id": account_id,
            "stop_on_reply": True,
            "steps": [step("invite"), step("message", template="Hi {{first_name|there}}")],
        },
        headers=auth(token),
    )

    assert response.status_code == 422
    problems = response.json()["error"]["details"]["problems"]
    assert any("if_accepted" in problem for problem in problems)


async def test_an_over_long_invite_note_is_refused(client: AsyncClient, db: Any) -> None:
    token, ws, account_id = await setup_workspace(client, db)

    response = await client.post(
        f"/api/v1/workspaces/{ws}/campaigns",
        json={
            "name": "Too long",
            "linkedin_account_id": account_id,
            "stop_on_reply": True,
            "steps": [step("invite", template="x" * 400)],
        },
        headers=auth(token),
    )

    assert response.status_code == 422
    problems = response.json()["error"]["details"]["problems"]
    assert any("300" in problem for problem in problems)


async def test_a_message_step_needs_a_body(client: AsyncClient, db: Any) -> None:
    token, ws, account_id = await setup_workspace(client, db)

    response = await client.post(
        f"/api/v1/workspaces/{ws}/campaigns",
        json={
            "name": "Empty message",
            "linkedin_account_id": account_id,
            "stop_on_reply": True,
            "steps": [step("invite"), step("message", only_if="if_accepted")],
        },
        headers=auth(token),
    )

    assert response.status_code == 422


async def test_a_sound_sequence_is_accepted(client: AsyncClient, db: Any) -> None:
    token, ws, account_id = await setup_workspace(client, db)

    response = await client.post(
        f"/api/v1/workspaces/{ws}/campaigns",
        json={
            "name": "Good sequence",
            "linkedin_account_id": account_id,
            "stop_on_reply": True,
            "steps": [
                step("view_profile"),
                step("invite", delay_hours=24, template="Hi {{first_name|there}}"),
                step(
                    "message",
                    delay_hours=48,
                    only_if="if_accepted",
                    template="Thanks for connecting, {{first_name|there}}",
                ),
            ],
        },
        headers=auth(token),
    )

    assert response.status_code == 201, response.text
    campaign = response.json()
    assert campaign["status"] == "draft"
    assert len(campaign["steps"]) == 3
    # Nothing can send yet, and the reason is stated plainly.
    assert any("Enroll" in blocker for blocker in campaign["launch_blockers"])


async def test_step_timing_round_trips_and_is_validated(client: AsyncClient, db: Any) -> None:
    token, ws, account_id = await setup_workspace(client, db)
    url = f"/api/v1/workspaces/{ws}/campaigns"

    good = await client.post(
        url,
        json={
            "name": "Timed",
            "linkedin_account_id": account_id,
            "steps": [
                step("view_profile", timing="asap"),
                step("invite", timing="at", send_at="2030-01-02T09:30:00+00:00", template="Hi"),
                step(
                    "message",
                    timing="delay",
                    delay_minutes=10,
                    only_if="if_accepted",
                    template="Thanks",
                ),
            ],
        },
        headers=auth(token),
    )
    assert good.status_code == 201, good.text
    steps = good.json()["steps"]
    assert [s["timing"] for s in steps] == ["asap", "at", "delay"]
    assert steps[1]["send_at"].startswith("2030-01-02T09:30:00")
    assert steps[2]["delay_minutes"] == 10

    missing_time = await client.post(
        url,
        json={
            "name": "Bad",
            "linkedin_account_id": account_id,
            "steps": [step("invite", timing="at", template="Hi")],
        },
        headers=auth(token),
    )
    assert missing_time.status_code in (400, 422)


# ── enrollment and launch ────────────────────────────────────────────────────


async def create_campaign(client: AsyncClient, token: str, ws: str, account_id: str) -> str:
    response = await client.post(
        f"/api/v1/workspaces/{ws}/campaigns",
        json={
            "name": "Demo",
            "linkedin_account_id": account_id,
            "stop_on_reply": True,
            "steps": [step("invite", template="Hi {{first_name|there}}")],
        },
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def test_launch_is_refused_without_leads(client: AsyncClient, db: Any) -> None:
    token, ws, account_id = await setup_workspace(client, db)
    campaign_id = await create_campaign(client, token, ws, account_id)

    response = await client.post(
        f"/api/v1/workspaces/{ws}/campaigns/{campaign_id}/status",
        json={"status": "running"},
        headers=auth(token),
    )

    assert response.status_code == 422
    assert "enroll" in response.json()["error"]["message"].lower()


async def test_enroll_then_launch(client: AsyncClient, db: Any) -> None:
    token, ws, account_id = await setup_workspace(client, db)
    campaign_id = await create_campaign(client, token, ws, account_id)
    list_id = await import_leads(client, token, ws, count=3)

    enrolled = await client.post(
        f"/api/v1/workspaces/{ws}/campaigns/{campaign_id}/enroll",
        json={"list_id": list_id},
        headers=auth(token),
    )
    assert enrolled.status_code == 200, enrolled.text
    assert enrolled.json()["enrolled"] == 3

    launched = await client.post(
        f"/api/v1/workspaces/{ws}/campaigns/{campaign_id}/status",
        json={"status": "running"},
        headers=auth(token),
    )
    assert launched.status_code == 200
    body = launched.json()
    assert body["status"] == "running"
    assert body["launch_blockers"] == []
    assert body["stats"]["enrolled"] == 3


async def test_enrolling_the_same_leads_twice_adds_nobody(client: AsyncClient, db: Any) -> None:
    token, ws, account_id = await setup_workspace(client, db)
    campaign_id = await create_campaign(client, token, ws, account_id)
    list_id = await import_leads(client, token, ws, count=3)

    first = await client.post(
        f"/api/v1/workspaces/{ws}/campaigns/{campaign_id}/enroll",
        json={"list_id": list_id},
        headers=auth(token),
    )
    second = await client.post(
        f"/api/v1/workspaces/{ws}/campaigns/{campaign_id}/enroll",
        json={"list_id": list_id},
        headers=auth(token),
    )

    assert first.json()["enrolled"] == 3
    assert second.json()["enrolled"] == 0
    assert second.json()["skipped_already_enrolled"] == 3


async def test_an_already_contacted_lead_is_not_enrolled(client: AsyncClient, db: Any) -> None:
    """The workspace-wide dedupe, enforced at enrollment."""
    token, ws, account_id = await setup_workspace(client, db)
    campaign_id = await create_campaign(client, token, ws, account_id)
    list_id = await import_leads(client, token, ws, count=3)

    from app.models.leads import ContactedLead

    db.add(ContactedLead(workspace_id=ws, public_id="lead-0-demo"))
    await db.flush()

    enrolled = await client.post(
        f"/api/v1/workspaces/{ws}/campaigns/{campaign_id}/enroll",
        json={"list_id": list_id},
        headers=auth(token),
    )

    assert enrolled.json()["enrolled"] == 2
    assert enrolled.json()["skipped_duplicate"] == 1


async def test_the_sequence_cannot_be_edited_while_running(client: AsyncClient, db: Any) -> None:
    token, ws, account_id = await setup_workspace(client, db)
    campaign_id = await create_campaign(client, token, ws, account_id)
    list_id = await import_leads(client, token, ws, count=2)
    await client.post(
        f"/api/v1/workspaces/{ws}/campaigns/{campaign_id}/enroll",
        json={"list_id": list_id},
        headers=auth(token),
    )
    await client.post(
        f"/api/v1/workspaces/{ws}/campaigns/{campaign_id}/status",
        json={"status": "running"},
        headers=auth(token),
    )

    response = await client.put(
        f"/api/v1/workspaces/{ws}/campaigns/{campaign_id}/steps",
        json=[step("invite", template="Different")],
        headers=auth(token),
    )

    assert response.status_code == 409
    assert "pause" in response.json()["error"]["message"].lower()


async def test_launch_is_refused_when_the_account_is_not_connected(
    client: AsyncClient, db: Any
) -> None:
    token, ws, account_id = await setup_workspace(client, db)
    campaign_id = await create_campaign(client, token, ws, account_id)
    list_id = await import_leads(client, token, ws, count=2)
    await client.post(
        f"/api/v1/workspaces/{ws}/campaigns/{campaign_id}/enroll",
        json={"list_id": list_id},
        headers=auth(token),
    )

    from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus

    account = await db.get(LinkedInAccount, account_id)
    account.status = LinkedInAccountStatus.AUTH_LOST
    await db.flush()

    response = await client.post(
        f"/api/v1/workspaces/{ws}/campaigns/{campaign_id}/status",
        json={"status": "running"},
        headers=auth(token),
    )

    assert response.status_code == 409
    assert "reconnect" in response.json()["error"]["message"].lower()


# ── template preview ─────────────────────────────────────────────────────────


async def test_template_preview_names_unsafe_variables(client: AsyncClient, db: Any) -> None:
    token, ws, _ = await setup_workspace(client, db)

    response = await client.post(
        f"/api/v1/workspaces/{ws}/campaigns/preview-template",
        json={"template": "Hi {{first_name}}, how is {{company|your team}}?"},
        headers=auth(token),
    )

    body = response.json()
    assert "Priya" in body["rendered"]
    assert body["variables"] == ["company", "first_name"]
    # Only the one without a fallback is flagged.
    assert body["variables_without_fallback"] == ["first_name"]
    assert body["exceeds_invite_limit"] is False


async def test_template_preview_flags_an_over_long_invite(client: AsyncClient, db: Any) -> None:
    token, ws, _ = await setup_workspace(client, db)

    response = await client.post(
        f"/api/v1/workspaces/{ws}/campaigns/preview-template",
        json={"template": "y" * 350},
        headers=auth(token),
    )

    assert response.json()["exceeds_invite_limit"] is True


async def test_spintax_resolves_in_the_preview(client: AsyncClient, db: Any) -> None:
    token, ws, _ = await setup_workspace(client, db)

    response = await client.post(
        f"/api/v1/workspaces/{ws}/campaigns/preview-template",
        json={"template": "{Hi|Hello} there"},
        headers=auth(token),
    )

    rendered = response.json()["rendered"]
    assert rendered in ("Hi there", "Hello there")


# ── quota status ─────────────────────────────────────────────────────────────


async def test_quota_status_explains_why_nothing_is_sending(client: AsyncClient, db: Any) -> None:
    token, ws, _ = await setup_workspace(client, db)

    response = await client.get(f"/api/v1/workspaces/{ws}/quota-status", headers=auth(token))

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["invites_used_today"] == 0
    # Test mode is on by default, so the cap is the small one.
    assert row["invites_limit_today"] <= 5
    assert row["invite_limit_reason"]


async def test_quota_status_reports_the_kill_switch(client: AsyncClient, db: Any) -> None:
    token, ws, _ = await setup_workspace(client, db)

    await client.patch(
        f"/api/v1/workspaces/{ws}", json={"outreach_paused": True}, headers=auth(token)
    )
    response = await client.get(f"/api/v1/workspaces/{ws}/quota-status", headers=auth(token))

    assert response.json()[0]["blocked_reason"] == "workspace kill switch is on"
