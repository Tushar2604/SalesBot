"""Integration layer: API keys on the REST API, and signed webhooks with retries."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import crypto
from app.integrations import events, webhooks
from app.models.integrations import DeliveryStatus, WebhookDelivery, WebhookEndpoint
from app.worker.tasks import webhooks as webhook_tasks
from tests.test_inbox import make_workspace
from tests.test_inbox_api import auth, register


def base(ws: str) -> str:
    return f"/api/v1/workspaces/{ws}/integrations"


async def new_key(client: AsyncClient, token: str, ws: str, role: str = "admin") -> str:
    created = await client.post(
        f"{base(ws)}/api-keys", json={"name": "Zapier", "role": role}, headers=auth(token)
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["secret"].startswith("sr_live_")
    assert body["key"]["prefix"] == body["secret"][: len(body["key"]["prefix"])]
    return str(body["secret"])


# ── API keys ─────────────────────────────────────────────────────────────────


async def test_an_api_key_opens_the_workspace_rest_api(client: AsyncClient, db: Any) -> None:
    token, ws = await register(client)
    key = await new_key(client, token, ws)

    via_bearer = await client.get(f"/api/v1/workspaces/{ws}/leads", headers=auth(key))
    assert via_bearer.status_code == 200, via_bearer.text
    via_header = await client.get(f"/api/v1/workspaces/{ws}/leads", headers={"X-API-Key": key})
    assert via_header.status_code == 200

    me = (await client.get(f"{base(ws)}/whoami", headers=auth(key))).json()
    assert me["via_api_key"] is True and me["api_key_name"] == "Zapier"
    assert me["workspace_id"] == ws


async def test_a_key_only_works_on_its_own_workspace(client: AsyncClient, db: Any) -> None:
    token, ws = await register(client)
    key = await new_key(client, token, ws)
    _, other_ws = await register(client, email="other@example.com")
    blocked = await client.get(f"/api/v1/workspaces/{other_ws}/leads", headers=auth(key))
    assert blocked.status_code == 404
    # Account-level endpoints need a person's own login.
    assert (await client.get("/api/v1/auth/me", headers=auth(key))).status_code == 401


async def test_a_revoked_or_made_up_key_is_refused(client: AsyncClient, db: Any) -> None:
    token, ws = await register(client)
    key = await new_key(client, token, ws)
    keys = (await client.get(f"{base(ws)}/api-keys", headers=auth(token))).json()
    revoked = await client.delete(f"{base(ws)}/api-keys/{keys[0]['id']}", headers=auth(token))
    assert revoked.json()["revoked_at"] is not None

    assert (
        await client.get(f"/api/v1/workspaces/{ws}/leads", headers=auth(key))
    ).status_code == 401
    fake = "sr_live_" + "x" * 43
    assert (
        await client.get(f"/api/v1/workspaces/{ws}/leads", headers=auth(fake))
    ).status_code == 401


async def test_a_key_cannot_mint_more_keys(client: AsyncClient, db: Any) -> None:
    token, ws = await register(client)
    key = await new_key(client, token, ws)
    minted = await client.post(
        f"{base(ws)}/api-keys", json={"name": "sneaky", "role": "admin"}, headers=auth(key)
    )
    assert minted.status_code == 403


async def test_a_member_key_has_member_powers_only(client: AsyncClient, db: Any) -> None:
    token, ws = await register(client)
    key = await new_key(client, token, ws, role="member")
    hook = await client.post(
        f"{base(ws)}/webhooks",
        json={"url": "https://example.com/hook", "events": ["*"]},
        headers=auth(key),
    )
    assert hook.status_code == 403  # webhooks need admin


async def test_owner_role_keys_are_not_offered(client: AsyncClient, db: Any) -> None:
    token, ws = await register(client)
    made = await client.post(
        f"{base(ws)}/api-keys", json={"name": "x", "role": "owner"}, headers=auth(token)
    )
    assert made.status_code == 422


async def test_keys_are_rate_limited(
    client: AsyncClient, db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.integrations import api_keys

    token, ws = await register(client)
    key = await new_key(client, token, ws)
    monkeypatch.setattr(api_keys.settings, "api_key_rate_limit_per_minute", 3)
    codes = [
        (await client.get(f"/api/v1/workspaces/{ws}/leads", headers=auth(key))).status_code
        for _ in range(5)
    ]
    assert codes[:3] == [200, 200, 200] and 429 in codes[3:]


async def test_only_the_hash_of_a_key_is_stored(client: AsyncClient, db: Any) -> None:
    from app.models.integrations import ApiKey

    token, ws = await register(client)
    key = await new_key(client, token, ws)
    row = (await db.execute(select(ApiKey))).scalars().first()
    assert row.key_hash != key and key not in row.key_hash and len(row.key_hash) == 64


# ── webhook endpoints ────────────────────────────────────────────────────────


async def test_webhook_crud_and_secret_shown_once(client: AsyncClient, db: Any) -> None:
    token, ws = await register(client)
    created = await client.post(
        f"{base(ws)}/webhooks",
        json={"url": "https://example.com/hook", "events": ["reply.received", "invite.accepted"]},
        headers=auth(token),
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["secret"].startswith("whsec_")
    hook_id = body["webhook"]["id"]
    listed = (await client.get(f"{base(ws)}/webhooks", headers=auth(token))).json()
    assert "secret" not in listed[0]

    rotated = (
        await client.post(f"{base(ws)}/webhooks/{hook_id}/rotate-secret", headers=auth(token))
    ).json()
    assert rotated["secret"] != body["secret"]

    patched = await client.patch(
        f"{base(ws)}/webhooks/{hook_id}", json={"events": ["*"]}, headers=auth(token)
    )
    assert patched.json()["events"] == ["*"]
    bad = await client.patch(
        f"{base(ws)}/webhooks/{hook_id}", json={"events": ["no.such"]}, headers=auth(token)
    )
    assert bad.status_code == 422
    assert (
        await client.delete(f"{base(ws)}/webhooks/{hook_id}", headers=auth(token))
    ).status_code == 204


async def test_internal_urls_are_refused_in_production(
    client: AsyncClient, db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A webhook URL makes our server send a request: it must not reach
    internal services (SSRF)."""
    monkeypatch.setattr(webhooks.settings, "webhooks_allow_private_urls", False)
    token, ws = await register(client)
    for url in (
        "http://example.com/hook",  # plain http
        "https://127.0.0.1/hook",
        "https://169.254.169.254/latest/meta-data",  # cloud metadata
        "https://10.0.0.5/internal",
        "https://user:pass@example.com/hook",
        "ftp://example.com/hook",
    ):
        made = await client.post(
            f"{base(ws)}/webhooks", json={"url": url, "events": ["*"]}, headers=auth(token)
        )
        assert made.status_code == 422, url


async def test_events_are_queued_only_for_subscribed_endpoints(
    client: AsyncClient, db: Any
) -> None:
    token, ws = await register(client)
    for events_wanted in (["lead.imported"], ["reply.received"]):
        await client.post(
            f"{base(ws)}/webhooks",
            json={"url": "https://example.com/hook", "events": events_wanted},
            headers=auth(token),
        )
    imported = await client.post(
        f"/api/v1/workspaces/{ws}/leads/import-urls",
        json={"urls": "https://www.linkedin.com/in/priya-s"},
        headers=auth(token),
    )
    assert imported.status_code == 201, imported.text

    rows = list((await db.execute(select(WebhookDelivery))).scalars())
    assert [r.event_type for r in rows] == ["lead.imported"]
    payload = rows[0].payload
    assert payload["type"] == "lead.imported" and payload["workspace_id"] == ws
    assert payload["data"]["imported"] == 1 and payload["data"]["source"] == "pasted_links"


async def test_test_event_and_retry(client: AsyncClient, db: Any) -> None:
    token, ws = await register(client)
    hook = (
        await client.post(
            f"{base(ws)}/webhooks",
            json={"url": "https://example.com/hook", "events": ["invite.sent"]},
            headers=auth(token),
        )
    ).json()["webhook"]
    sent = await client.post(f"{base(ws)}/webhooks/{hook['id']}/test", headers=auth(token))
    assert sent.status_code == 202 and sent.json()["event_type"] == "webhook.test"

    delivery_id = sent.json()["id"]
    row = await db.get(WebhookDelivery, uuid.UUID(delivery_id))
    row.status = DeliveryStatus.FAILED
    row.attempts = 7
    await db.flush()
    retried = await client.post(f"{base(ws)}/deliveries/{delivery_id}/retry", headers=auth(token))
    assert retried.json()["status"] == "pending" and retried.json()["attempts"] == 0


# ── signing and delivery ─────────────────────────────────────────────────────


def test_signatures_verify_and_reject_tampering_and_replays() -> None:
    body = b'{"type":"reply.received"}'
    header = webhooks.sign("whsec_abc", body)
    assert webhooks.verify("whsec_abc", body, header)
    assert not webhooks.verify("whsec_abc", body + b" ", header)  # tampered body
    assert not webhooks.verify("whsec_other", body, header)  # wrong secret
    old = webhooks.sign("whsec_abc", body, timestamp=int(datetime.now(UTC).timestamp()) - 3600)
    assert not webhooks.verify("whsec_abc", body, old)  # replayed an hour later


def _endpoint(db: Session, url: str = "https://receiver.example/hook") -> WebhookEndpoint:
    workspace = make_workspace(db)
    endpoint = WebhookEndpoint(
        workspace_id=workspace.id,
        url=url,
        events=["*"],
        secret_ciphertext=crypto.encrypt_str("whsec_test"),
        enabled=True,
    )
    db.add(endpoint)
    db.flush()
    return endpoint


def _delivery(db: Session, endpoint: WebhookEndpoint) -> WebhookDelivery:
    events.emit_sync(db, endpoint.workspace_id, "reply.received", {"text": "Sounds good!"})
    db.flush()
    row = db.execute(
        select(WebhookDelivery).where(WebhookDelivery.endpoint_id == endpoint.id)
    ).scalar_one()
    row.status = DeliveryStatus.SENDING
    return row


def test_a_delivery_is_signed_and_marked_delivered(sdb: Session) -> None:
    endpoint = _endpoint(sdb)
    delivery = _delivery(sdb, endpoint)
    seen: list[httpx.Request] = []

    def receiver(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, text="ok")

    status = webhook_tasks.run_delivery(sdb, delivery, transport=httpx.MockTransport(receiver))
    assert status == "succeeded"
    request = seen[0]
    assert request.headers["X-SalesRobo-Event"] == "reply.received"
    assert webhooks.verify("whsec_test", request.content, request.headers["X-SalesRobo-Signature"])
    assert json.loads(request.content)["data"] == {"text": "Sounds good!"}
    assert endpoint.failure_streak == 0 and endpoint.last_success_at is not None


def test_failures_back_off_then_give_up(sdb: Session) -> None:
    endpoint = _endpoint(sdb)
    delivery = _delivery(sdb, endpoint)
    down = httpx.MockTransport(lambda r: httpx.Response(503, text="maintenance"))

    before = datetime.now(UTC)
    assert webhook_tasks.run_delivery(sdb, delivery, transport=down) == "pending"
    assert delivery.next_attempt_at >= before + timedelta(seconds=55)
    assert delivery.response_status == 503 and "503" in delivery.error

    for _ in range(webhook_tasks.MAX_ATTEMPTS - 1):
        delivery.status = DeliveryStatus.SENDING
        webhook_tasks.run_delivery(sdb, delivery, transport=down)
    assert delivery.status is DeliveryStatus.FAILED
    assert delivery.attempts == webhook_tasks.MAX_ATTEMPTS


def test_redirects_are_not_followed(sdb: Session) -> None:
    endpoint = _endpoint(sdb)
    delivery = _delivery(sdb, endpoint)
    redirecting = httpx.MockTransport(
        lambda r: httpx.Response(302, headers={"Location": "http://169.254.169.254/"})
    )
    webhook_tasks.run_delivery(sdb, delivery, transport=redirecting)
    assert delivery.status is DeliveryStatus.PENDING and "redirect" in delivery.error


def test_an_endpoint_that_keeps_failing_is_switched_off(
    sdb: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(webhook_tasks, "DISABLE_AFTER_STREAK", 2)
    endpoint = _endpoint(sdb)
    delivery = _delivery(sdb, endpoint)
    down = httpx.MockTransport(lambda r: httpx.Response(500))
    webhook_tasks.run_delivery(sdb, delivery, transport=down)
    delivery.status = DeliveryStatus.SENDING
    webhook_tasks.run_delivery(sdb, delivery, transport=down)
    assert endpoint.enabled is False and "failed attempts" in endpoint.disabled_reason
    assert delivery.status is DeliveryStatus.FAILED


def test_the_sweep_claims_due_deliveries_once(
    sdb: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_inbox import _bind_session_scope

    endpoint = _endpoint(sdb)
    events.emit_sync(sdb, endpoint.workspace_id, "invite.sent", {})
    sdb.flush()
    sent: list[str] = []
    monkeypatch.setattr(
        webhook_tasks.deliver, "apply_async", lambda args, **k: sent.append(args[0])
    )
    with _bind_session_scope(monkeypatch, webhook_tasks, sdb):
        first = webhook_tasks.deliver_due()
        second = webhook_tasks.deliver_due()
    assert first["claimed"] == 1 and second["claimed"] == 0
    assert len(sent) == 1


def test_unknown_event_types_are_a_programming_error(sdb: Session) -> None:
    endpoint = _endpoint(sdb)
    with pytest.raises(ValueError):
        events.emit_sync(sdb, endpoint.workspace_id, "made.up", {})
