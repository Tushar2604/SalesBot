"""Assistant HTTP endpoints: settings, knowledge base, and the controls a person
uses to take over from the bot in the inbox."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient

from tests.test_inbox_api import auth, make_conversation, register, sent_tasks  # noqa: F401


async def test_settings_start_off_and_can_be_changed(client: AsyncClient, db: Any) -> None:
    token, ws = await register(client)
    url = f"/api/v1/workspaces/{ws}/assistant/settings"

    first = await client.get(url, headers=auth(token))
    assert first.status_code == 200
    assert first.json()["mode"] == "off"

    updated = await client.put(
        url,
        json={"mode": "draft", "persona": "Priya, HR at Acme", "max_replies_per_thread_per_day": 2},
        headers=auth(token),
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert body["mode"] == "draft" and body["persona"] == "Priya, HR at Acme"
    assert body["max_replies_per_thread_per_day"] == 2

    again = await client.get(url, headers=auth(token))
    assert again.json()["mode"] == "draft"


async def test_knowledge_base_crud(client: AsyncClient, db: Any) -> None:
    token, ws = await register(client)
    base = f"/api/v1/workspaces/{ws}/assistant/knowledge"

    created = await client.post(
        base,
        json={"title": "Backend Engineer JD", "content": "Python, FastAPI, 3+ years. Remote."},
        headers=auth(token),
    )
    assert created.status_code == 201, created.text
    item_id = created.json()["id"]

    patched = await client.patch(f"{base}/{item_id}", json={"enabled": False}, headers=auth(token))
    assert patched.json()["enabled"] is False

    listed = await client.get(base, headers=auth(token))
    assert [i["title"] for i in listed.json()] == ["Backend Engineer JD"]

    deleted = await client.delete(f"{base}/{item_id}", headers=auth(token))
    assert deleted.status_code == 204
    assert (await client.get(base, headers=auth(token))).json() == []


async def test_try_it_reports_unavailable_without_a_key(client: AsyncClient, db: Any) -> None:
    token, ws = await register(client)
    response = await client.post(
        f"/api/v1/workspaces/{ws}/assistant/try",
        json={"turns": [{"from_me": False, "text": "Can you share the JD?"}]},
        headers=auth(token),
    )
    assert response.status_code == 200
    assert response.json()["action"] == "unavailable"


async def test_replying_yourself_pauses_the_bot(client: AsyncClient, db: Any, sent_tasks) -> None:  # noqa: F811
    token, ws = await register(client)
    conversation_id = await make_conversation(db, ws)

    reply = await client.post(
        f"/api/v1/workspaces/{ws}/conversations/{conversation_id}/reply",
        json={"text": "I'll take this one."},
        headers=auth(token),
    )
    assert reply.status_code == 200, reply.text
    assert reply.json()["bot_paused"] is True
    assert reply.json()["bot_pause_reason"] == "You replied yourself"
    assert sent_tasks[-1]["args"][1] == "I'll take this one."


async def test_sending_a_draft_keeps_the_bot_on(client: AsyncClient, db: Any, sent_tasks) -> None:  # noqa: F811
    token, ws = await register(client)
    conversation_id = await make_conversation(db, ws)

    response = await client.post(
        f"/api/v1/workspaces/{ws}/conversations/{conversation_id}/bot/send-draft",
        json={"text": "Here's the JD: Python, 3+ years."},
        headers=auth(token),
    )
    assert response.status_code == 200, response.text
    assert response.json()["bot_paused"] is False
    assert sent_tasks[-1] == {
        "name": "linkedin.action.send_reply",
        "args": [conversation_id, "Here's the JD: Python, 3+ years.", "bot"],
    }


async def test_typing_and_resume(client: AsyncClient, db: Any, sent_tasks) -> None:  # noqa: F811
    token, ws = await register(client)
    conversation_id = await make_conversation(db, ws)
    base = f"/api/v1/workspaces/{ws}/conversations/{conversation_id}"

    typing = await client.post(f"{base}/typing", headers=auth(token))
    assert typing.status_code == 204

    paused = await client.post(f"{base}/bot", json={"paused": True}, headers=auth(token))
    assert paused.json()["bot_paused"] is True

    resumed = await client.post(f"{base}/bot", json={"paused": False}, headers=auth(token))
    assert resumed.json()["bot_paused"] is False
    # Resuming answers anything left unanswered.
    assert sent_tasks[-1] == {"name": "assistant.respond", "args": [conversation_id]}
