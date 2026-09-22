"""Inbox HTTP endpoints: pagination, filtering, auth, and tenant isolation."""

from __future__ import annotations

from datetime import UTC, datetime
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


async def register(client: AsyncClient, email: str = "owner@example.com") -> tuple[str, str]:
    signup = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": "correct horse 7",
            "full_name": "Owner",
            "workspace_name": "Acme",
        },
    )
    token = signup.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers=auth(token))
    return token, me.json()["workspaces"][0]["workspace"]["id"]


async def make_conversation(
    db: Any,
    workspace_id: str,
    *,
    label: str = "none",
    unread: bool = False,
    text: str = "Hi there, interested to learn more",
) -> str:
    from app.linkedin import caps as caps_mod
    from app.models.inbox import Conversation, ConversationLabel, Message, MessageDirection
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

    conversation = Conversation(
        workspace_id=workspace_id,
        linkedin_account_id=account.id,
        conversation_urn=f"urn:li:fsd_conversation:{account.id}",
        participant_urn="urn:li:fsd_profile:lead1",
        participant_name="Lead One",
        last_message_at=datetime.now(UTC),
        last_message_text=text,
        last_message_from_me=False,
        unread=unread,
        label=ConversationLabel(label),
    )
    db.add(conversation)
    await db.flush()
    db.add(
        Message(
            workspace_id=workspace_id,
            conversation_id=conversation.id,
            direction=MessageDirection.INBOUND,
            body=text,
            sent_at=datetime.now(UTC),
        )
    )
    await db.flush()
    return str(conversation.id)


async def test_list_conversations_is_workspace_scoped(client: AsyncClient, db: Any) -> None:
    token, ws = await register(client)
    await make_conversation(db, ws)

    outsider_token, _ = await register(client, "outsider@example.org")

    mine = await client.get(f"/api/v1/workspaces/{ws}/conversations", headers=auth(token))
    assert mine.status_code == 200
    assert mine.json()["total"] == 1

    theirs = await client.get(f"/api/v1/workspaces/{ws}/conversations", headers=auth(outsider_token))
    assert theirs.status_code == 404


async def test_list_conversations_filters_by_label_and_unread(client: AsyncClient, db: Any) -> None:
    token, ws = await register(client)
    await make_conversation(db, ws, label="interested", unread=True)
    await make_conversation(db, ws, label="not_interested", unread=False)

    by_label = await client.get(
        f"/api/v1/workspaces/{ws}/conversations",
        params={"label": "interested"},
        headers=auth(token),
    )
    assert by_label.status_code == 200
    assert by_label.json()["total"] == 1

    unread = await client.get(
        f"/api/v1/workspaces/{ws}/conversations",
        params={"unread_only": True},
        headers=auth(token),
    )
    assert unread.status_code == 200
    assert unread.json()["total"] == 1


async def test_get_messages_ordered_and_workspace_scoped(client: AsyncClient, db: Any) -> None:
    token, ws = await register(client)
    conversation_id = await make_conversation(db, ws)
    outsider_token, _ = await register(client, "outsider2@example.org")

    response = await client.get(
        f"/api/v1/workspaces/{ws}/conversations/{conversation_id}/messages", headers=auth(token)
    )
    assert response.status_code == 200
    assert len(response.json()) == 1

    blocked = await client.get(
        f"/api/v1/workspaces/{ws}/conversations/{conversation_id}/messages",
        headers=auth(outsider_token),
    )
    assert blocked.status_code == 404


async def test_reply_dispatches_worker_task(
    client: AsyncClient, db: Any, sent_tasks: list[dict[str, Any]]
) -> None:
    token, ws = await register(client)
    conversation_id = await make_conversation(db, ws)

    response = await client.post(
        f"/api/v1/workspaces/{ws}/conversations/{conversation_id}/reply",
        json={"text": "Thanks, let's set up a call"},
        headers=auth(token),
    )

    assert response.status_code == 200, response.text
    assert sent_tasks == [
        {"name": "linkedin.action.send_reply", "args": [conversation_id, "Thanks, let's set up a call"]}
    ]


async def test_reply_rejects_empty_text(client: AsyncClient, db: Any) -> None:
    token, ws = await register(client)
    conversation_id = await make_conversation(db, ws)

    response = await client.post(
        f"/api/v1/workspaces/{ws}/conversations/{conversation_id}/reply",
        json={"text": "   "},
        headers=auth(token),
    )
    assert response.status_code == 422


async def test_label_persists_and_audits(client: AsyncClient, db: Any) -> None:
    from sqlalchemy import select

    from app.models.tenancy import AuditEvent

    token, ws = await register(client)
    conversation_id = await make_conversation(db, ws)

    response = await client.post(
        f"/api/v1/workspaces/{ws}/conversations/{conversation_id}/label",
        json={"label": "interested"},
        headers=auth(token),
    )
    assert response.status_code == 200
    assert response.json()["label"] == "interested"
    assert response.json()["label_source"] == "manual"

    events = (
        (await db.execute(select(AuditEvent).where(AuditEvent.action == "inbox.label_set")))
        .scalars()
        .all()
    )
    assert len(events) == 1


async def test_snooze_and_unsnooze(client: AsyncClient, db: Any) -> None:
    token, ws = await register(client)
    conversation_id = await make_conversation(db, ws)

    snoozed = await client.post(
        f"/api/v1/workspaces/{ws}/conversations/{conversation_id}/snooze",
        json={"until": "2026-12-01T00:00:00Z"},
        headers=auth(token),
    )
    assert snoozed.status_code == 200
    assert snoozed.json()["snoozed_until"] is not None

    unsnoozed = await client.post(
        f"/api/v1/workspaces/{ws}/conversations/{conversation_id}/snooze",
        json={"until": None},
        headers=auth(token),
    )
    assert unsnoozed.status_code == 200
    assert unsnoozed.json()["snoozed_until"] is None


async def test_mark_read(client: AsyncClient, db: Any) -> None:
    token, ws = await register(client)
    conversation_id = await make_conversation(db, ws, unread=True)

    response = await client.post(
        f"/api/v1/workspaces/{ws}/conversations/{conversation_id}/read", headers=auth(token)
    )
    assert response.status_code == 200
    assert response.json()["unread"] is False


async def test_cross_workspace_conversation_is_404(client: AsyncClient, db: Any) -> None:
    token, ws = await register(client)
    conversation_id = await make_conversation(db, ws)
    outsider_token, outsider_ws = await register(client, "outsider3@example.org")

    response = await client.get(
        f"/api/v1/workspaces/{outsider_ws}/conversations/{conversation_id}",
        headers=auth(outsider_token),
    )
    assert response.status_code == 404
