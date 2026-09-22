"""LinkedIn account endpoints.

Celery is stubbed out: these tests assert what the API persists and returns, and
that it enqueues the right task with an *encrypted* payload. What the worker
then does to LinkedIn is a separate concern with separate tests.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient

from app.core.crypto import decrypt_json


@pytest.fixture
def sent_tasks(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Captures Celery dispatches instead of publishing them."""
    captured: list[dict[str, Any]] = []

    def fake_send_task(name: str, *args: Any, **kwargs: Any) -> object:
        captured.append({"name": name, "args": kwargs.get("args") or (args[0] if args else [])})

        class _Result:
            id = "stubbed"

        return _Result()

    from app.worker import celery_app as celery_module

    monkeypatch.setattr(celery_module.celery_app, "send_task", fake_send_task)
    return captured


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
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return token, me.json()["workspaces"][0]["workspace"]["id"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_connect_with_cookie_persists_account_and_enqueues_encrypted_secret(
    client: AsyncClient, sent_tasks: list[dict[str, Any]]
) -> None:
    token, ws = await register(client)

    response = await client.post(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/connect/cookie",
        json={"label": "Founder profile", "li_at": "AQEDAT" + "x" * 40, "timezone": "Asia/Kolkata"},
        headers=auth(token),
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["next_step"] == "poll"
    account = body["account"]
    assert account["status"] == "connecting"
    assert account["test_mode"] is True
    # A device identity is frozen at creation, before LinkedIn is ever contacted.
    assert account["device"] and "Android" in account["device"]
    assert account["using_direct_connection"] is True
    assert any("server's IP" in w for w in account["warnings"])

    assert len(sent_tasks) == 1
    task = sent_tasks[0]
    assert task["name"] == "linkedin.auth.connect_cookie"

    # The cookie must not travel through the broker in plaintext.
    sealed = task["args"][1]
    assert "AQEDAT" not in sealed
    assert decrypt_json(base64.b64decode(sealed))["li_at"] == "AQEDAT" + "x" * 40


async def test_cookie_input_tolerates_a_pasted_name_equals_value(
    client: AsyncClient, sent_tasks: list[dict[str, Any]]
) -> None:
    token, ws = await register(client)

    await client.post(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/connect/cookie",
        json={"li_at": 'li_at="AQEDATpasted00000000000000000000"', "timezone": "UTC"},
        headers=auth(token),
    )

    sealed = sent_tasks[0]["args"][1]
    assert decrypt_json(base64.b64decode(sealed))["li_at"] == "AQEDATpasted00000000000000000000"


async def test_password_is_encrypted_for_transit(
    client: AsyncClient, sent_tasks: list[dict[str, Any]]
) -> None:
    token, ws = await register(client)

    response = await client.post(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/connect/credentials",
        json={"email": "me@example.com", "password": "s3cret-linkedin-pw", "timezone": "UTC"},
        headers=auth(token),
    )

    assert response.status_code == 201
    sealed = sent_tasks[0]["args"][1]
    assert "s3cret" not in sealed
    assert decrypt_json(base64.b64decode(sealed))["password"] == "s3cret-linkedin-pw"


async def _connect(client: AsyncClient, token: str, ws: str, seed: str) -> str:
    created = await client.post(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/connect/cookie",
        json={"li_at": "AQEDAT" + seed * 40, "timezone": "UTC"},
        headers=auth(token),
    )
    return str(created.json()["account"]["id"])


async def test_an_absurd_cap_is_rejected_at_the_edge(
    client: AsyncClient, sent_tasks: list[dict[str, Any]]
) -> None:
    """Two layers guard limits. This is the outer one: schema validation."""
    token, ws = await register(client)
    account_id = await _connect(client, token, ws, "y")

    response = await client.patch(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/{account_id}",
        json={"daily_invites": 500},
        headers=auth(token),
    )

    assert response.status_code == 422


async def test_an_in_range_cap_is_clamped_by_the_ramp_curve(
    client: AsyncClient, sent_tasks: list[dict[str, Any]]
) -> None:
    """And this is the inner one: a plausible number still cannot beat the ramp."""
    token, ws = await register(client)
    account_id = await _connect(client, token, ws, "y")

    response = await client.patch(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/{account_id}",
        json={"daily_invites": 75, "test_mode": False},
        headers=auth(token),
    )

    assert response.status_code == 200
    caps = response.json()["caps"]
    # A brand-new account is held to the first rung of the ramp curve.
    assert caps["daily_invites"] == 12
    assert caps["invite_limit_reason"] == "account warm-up curve"


async def test_working_hours_must_be_ordered(
    client: AsyncClient, sent_tasks: list[dict[str, Any]]
) -> None:
    token, ws = await register(client)
    created = await client.post(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/connect/cookie",
        json={"li_at": "AQEDAT" + "z" * 40, "timezone": "UTC"},
        headers=auth(token),
    )
    account_id = created.json()["account"]["id"]

    response = await client.patch(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/{account_id}",
        json={"working_hours": {"start": "18:00", "end": "09:00"}},
        headers=auth(token),
    )

    assert response.status_code == 422
    assert "before they end" in response.json()["error"]["message"]


async def test_proxy_credentials_are_never_returned(
    client: AsyncClient, sent_tasks: list[dict[str, Any]]
) -> None:
    token, ws = await register(client)

    created = await client.post(
        f"/api/v1/workspaces/{ws}/proxies",
        json={
            "label": "Residential IN",
            "host": "proxy.example.com",
            "port": 8000,
            "username": "proxy-user",
            "password": "proxy-pass",
            "country": "in",
        },
        headers=auth(token),
    )

    assert created.status_code == 201
    body = created.json()
    assert body["country"] == "IN"
    assert body["public_url"] == "http://proxy.example.com:8000"
    assert body["assigned_account_id"] is None

    listed = (await client.get(f"/api/v1/workspaces/{ws}/proxies", headers=auth(token))).text
    assert "proxy-user" not in listed
    assert "proxy-pass" not in listed


async def test_a_proxy_cannot_be_bound_to_two_accounts(
    client: AsyncClient, sent_tasks: list[dict[str, Any]]
) -> None:
    """One account per IP. Two accounts on one exit IP is a clustering signal."""
    token, ws = await register(client)
    proxy_id = (
        await client.post(
            f"/api/v1/workspaces/{ws}/proxies",
            json={"host": "proxy.example.com", "port": 8000, "country": "IN"},
            headers=auth(token),
        )
    ).json()["id"]

    first = await client.post(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/connect/cookie",
        json={"li_at": "AQEDAT" + "a" * 40, "timezone": "UTC", "proxy_id": proxy_id},
        headers=auth(token),
    )
    assert first.status_code == 201
    assert first.json()["account"]["using_direct_connection"] is False

    second = await client.post(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/connect/cookie",
        json={"li_at": "AQEDAT" + "b" * 40, "timezone": "UTC", "proxy_id": proxy_id},
        headers=auth(token),
    )
    assert second.status_code == 409
    assert "already bound" in second.json()["error"]["message"]


async def test_a_bound_proxy_cannot_be_deleted(
    client: AsyncClient, sent_tasks: list[dict[str, Any]]
) -> None:
    token, ws = await register(client)
    proxy_id = (
        await client.post(
            f"/api/v1/workspaces/{ws}/proxies",
            json={"host": "proxy.example.com", "port": 8000},
            headers=auth(token),
        )
    ).json()["id"]
    await client.post(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/connect/cookie",
        json={"li_at": "AQEDAT" + "c" * 40, "timezone": "UTC", "proxy_id": proxy_id},
        headers=auth(token),
    )

    response = await client.delete(
        f"/api/v1/workspaces/{ws}/proxies/{proxy_id}", headers=auth(token)
    )
    assert response.status_code == 409


async def test_challenge_code_is_rejected_when_none_is_pending(
    client: AsyncClient, sent_tasks: list[dict[str, Any]]
) -> None:
    token, ws = await register(client)
    account_id = (
        await client.post(
            f"/api/v1/workspaces/{ws}/linkedin-accounts/connect/cookie",
            json={"li_at": "AQEDAT" + "d" * 40, "timezone": "UTC"},
            headers=auth(token),
        )
    ).json()["account"]["id"]

    response = await client.post(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/{account_id}/challenge",
        json={"code": "123456"},
        headers=auth(token),
    )

    assert response.status_code == 409
    assert "not waiting" in response.json()["error"]["message"]


async def test_members_cannot_connect_accounts(
    client: AsyncClient, sent_tasks: list[dict[str, Any]]
) -> None:
    owner_token, ws = await register(client)
    invite = await client.post(
        f"/api/v1/workspaces/{ws}/invites",
        json={"email": "rep@example.com", "role": "member"},
        headers=auth(owner_token),
    )
    rep_token = (
        await client.post(
            "/api/v1/auth/accept-invite",
            json={
                "token": invite.json()["invite_url"].rsplit("/", 1)[1],
                "password": "another pass 9",
            },
        )
    ).json()["access_token"]

    response = await client.post(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/connect/cookie",
        json={"li_at": "AQEDAT" + "e" * 40, "timezone": "UTC"},
        headers=auth(rep_token),
    )

    assert response.status_code == 403
    assert sent_tasks == []


async def test_another_tenant_cannot_see_your_accounts(
    client: AsyncClient, sent_tasks: list[dict[str, Any]]
) -> None:
    owner_token, ws = await register(client, "owner@example.com")
    await client.post(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/connect/cookie",
        json={"li_at": "AQEDAT" + "f" * 40, "timezone": "UTC"},
        headers=auth(owner_token),
    )
    outsider_token, _ = await register(client, "outsider@example.org")

    response = await client.get(
        f"/api/v1/workspaces/{ws}/linkedin-accounts", headers=auth(outsider_token)
    )

    assert response.status_code == 404


async def test_disconnect_clears_the_session_but_keeps_the_account(
    client: AsyncClient, sent_tasks: list[dict[str, Any]]
) -> None:
    token, ws = await register(client)
    account_id = (
        await client.post(
            f"/api/v1/workspaces/{ws}/linkedin-accounts/connect/cookie",
            json={"li_at": "AQEDAT" + "g" * 40, "timezone": "UTC"},
            headers=auth(token),
        )
    ).json()["account"]["id"]

    response = await client.post(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/{account_id}/disconnect",
        headers=auth(token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "disconnected"
    assert body["is_connected"] is False
    # The frozen device identity survives: reconnecting with a *new* device
    # would itself look suspicious to LinkedIn.
    assert body["device"] and "Android" in body["device"]


async def test_deleting_an_account_removes_it(
    client: AsyncClient, sent_tasks: list[dict[str, Any]]
) -> None:
    token, ws = await register(client)
    account_id = (
        await client.post(
            f"/api/v1/workspaces/{ws}/linkedin-accounts/connect/cookie",
            json={"li_at": "AQEDAT" + "h" * 40, "timezone": "UTC"},
            headers=auth(token),
        )
    ).json()["account"]["id"]

    response = await client.delete(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/{account_id}", headers=auth(token)
    )
    assert response.status_code in (200, 204)

    listed = await client.get(f"/api/v1/workspaces/{ws}/linkedin-accounts", headers=auth(token))
    assert account_id not in [a["id"] for a in listed.json()]


# ── idempotent connect ────────────────────────────────────────────────────────


async def test_connecting_with_credentials_twice_reuses_the_same_account(
    client: AsyncClient, sent_tasks: list[dict[str, Any]]
) -> None:
    """Pasting the same email twice must not create a second row.

    This is the pre-check that runs before any network call — it catches the
    common case (retry, accidental double-click) immediately, without waiting
    on a worker round trip.
    """
    token, ws = await register(client)
    payload = {
        "label": "Founder profile",
        "email": "founder@linkedin.example",
        "password": "correct horse battery staple 7",
        "timezone": "UTC",
    }

    first = await client.post(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/connect/credentials",
        json=payload,
        headers=auth(token),
    )
    second = await client.post(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/connect/credentials",
        json=payload,
        headers=auth(token),
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["account"]["id"] == second.json()["account"]["id"]

    listed = await client.get(f"/api/v1/workspaces/{ws}/linkedin-accounts", headers=auth(token))
    assert len(listed.json()) == 1

    # Both attempts still enqueue a fresh sign-in — a stuck/failed first
    # attempt must be retryable — but always against the same account id.
    assert len(sent_tasks) == 2
    assert sent_tasks[0]["args"][0] == sent_tasks[1]["args"][0]


async def test_connecting_a_different_email_creates_a_separate_account(
    client: AsyncClient, sent_tasks: list[dict[str, Any]]
) -> None:
    token, ws = await register(client)

    for email in ("first@linkedin.example", "second@linkedin.example"):
        await client.post(
            f"/api/v1/workspaces/{ws}/linkedin-accounts/connect/credentials",
            json={"email": email, "password": "correct horse battery staple 7", "timezone": "UTC"},
            headers=auth(token),
        )

    listed = await client.get(f"/api/v1/workspaces/{ws}/linkedin-accounts", headers=auth(token))
    assert len(listed.json()) == 2


def test_a_second_connect_resolving_to_the_same_profile_disconnects_the_first(
    sdb: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The authoritative dedup: two rows that turn out to be the same LinkedIn
    profile, discovered only once the worker actually signs in (this is what
    a cookie-based reconnect — no email known up front — relies on).
    """
    import uuid as uuid_mod

    from app.linkedin import caps as caps_mod
    from app.linkedin import fingerprint as fp_mod
    from app.linkedin.classify import Classification, ResponseClass
    from app.linkedin.driver import AuthResult, ProfileSnapshot, SessionBundle
    from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus
    from app.models.tenancy import Workspace
    from app.worker.tasks import linkedin_auth

    workspace = Workspace(name="Acme", slug=f"acme-{uuid_mod.uuid4().hex[:8]}")
    sdb.add(workspace)
    sdb.flush()

    def make_account(label: str) -> LinkedInAccount:
        account = LinkedInAccount(
            workspace_id=workspace.id,
            label=label,
            status=LinkedInAccountStatus.CONNECTING,
            fingerprint=fp_mod.generate(),
            caps=caps_mod.default_caps(),
            timezone="UTC",
        )
        sdb.add(account)
        sdb.flush()
        return account

    older = make_account("First attempt")
    newer = make_account("Second attempt")
    sdb.commit()

    profile = ProfileSnapshot(
        urn="urn:li:fsd_profile:same_person", public_id="same-person", first_name="Jane"
    )
    session = SessionBundle(cookies={"li_at": "x"}, csrf_token="t", established_at=datetime.now(UTC))
    result = AuthResult(classification=Classification(ResponseClass.OK), session=session)

    class FakeDriver:
        def verify_session(self):
            return Classification(ResponseClass.OK), profile

        def close(self):
            pass

    monkeypatch.setattr(linkedin_auth, "build_driver", lambda account: FakeDriver())
    linkedin_auth._finalize(sdb, older, result, source="cookie")
    sdb.commit()
    linkedin_auth._finalize(sdb, newer, result, source="cookie")
    sdb.commit()

    sdb.refresh(older)
    sdb.refresh(newer)

    assert newer.status is LinkedInAccountStatus.ACTIVE
    assert newer.profile_urn == "urn:li:fsd_profile:same_person"
    assert older.status is LinkedInAccountStatus.DISCONNECTED
    assert older.session_ciphertext is None
