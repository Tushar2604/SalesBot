"""Content Studio API: drafts, media, scheduling, permissions, isolation.

Celery and object storage are stubbed. What these tests assert is what the API
persists, what it refuses, and what it hands to the worker — the worker's own
behaviour has its own file.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.linkedin.publishing import POST_SCOPE
from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus
from app.models.tenancy import WorkspaceMember, WorkspaceRole

# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sent_tasks(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    captured: list[dict[str, Any]] = []

    def fake_send_task(name: str, *args: Any, **kwargs: Any) -> object:
        captured.append({"name": name, "args": kwargs.get("args") or (args[0] if args else [])})

        class _Result:
            id = "stubbed"

        return _Result()

    from app.worker import celery_app as celery_module

    monkeypatch.setattr(celery_module.celery_app, "send_task", fake_send_task)
    return captured


@pytest.fixture
def storage(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """In-memory stand-in for S3, so uploads are testable without MinIO."""
    objects: dict[str, bytes] = {}

    from app.services import media_service

    monkeypatch.setattr(
        media_service, "_put_sync", lambda key, body, ct: objects.__setitem__(key, body)
    )
    monkeypatch.setattr(media_service, "_get_sync", lambda key: objects[key])
    monkeypatch.setattr(media_service, "_delete_sync", lambda key: objects.pop(key, None))
    monkeypatch.setattr(media_service, "_presign_sync", lambda key, ttl: f"https://signed/{key}")
    return objects


@pytest.fixture
def publishing_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretends the deployment has a LinkedIn app registered."""
    from app.config import settings

    monkeypatch.setattr(settings, "linkedin_client_id", "test-client")
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "linkedin_client_secret", SecretStr("test-secret"))


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def register(
    client: AsyncClient, email: str = "owner@example.com", workspace: str = "Acme"
) -> tuple[str, str]:
    signup = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": "correct horse 7",
            "full_name": "Owner Person",
            "workspace_name": workspace,
        },
    )
    token = signup.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers=auth(token))
    return token, me.json()["workspaces"][0]["workspace"]["id"]


async def make_account(
    db: AsyncSession, workspace_id: str, *, granted: bool = True, label: str = "Founder"
) -> LinkedInAccount:
    """A LinkedIn account, optionally holding a publishing grant."""
    from app.core.crypto import encrypt_str

    account = LinkedInAccount(
        workspace_id=uuid.UUID(workspace_id),
        label=label,
        full_name="Tushar Anand",
        headline="Software Engineer",
        public_id="tushar",
        status=LinkedInAccountStatus.ACTIVE,
        proxy=None,
    )
    if granted:
        account.publishing_token_ciphertext = encrypt_str("a-member-token")
        account.publishing_scopes = ["openid", "profile", POST_SCOPE]
        account.publishing_member_urn = "urn:li:person:abc123"
        account.publishing_authorized_at = datetime.now(UTC)
        account.publishing_token_expires_at = datetime.now(UTC) + timedelta(days=30)
    db.add(account)
    await db.flush()
    return account


async def create_draft(
    client: AsyncClient, token: str, ws: str, account_id: str, content: str = "Hello LinkedIn"
) -> dict[str, Any]:
    response = await client.post(
        f"/api/v1/workspaces/{ws}/content/posts",
        json={"linkedin_account_id": account_id, "content": content},
        headers=auth(token),
    )
    assert response.status_code == 201, response.text
    return response.json()


# ── drafts ───────────────────────────────────────────────────────────────────


async def test_create_draft_persists_and_counts_text(
    client: AsyncClient, db: AsyncSession
) -> None:
    token, ws = await register(client)
    account = await make_account(db, ws)

    post = await create_draft(
        client, token, ws, str(account.id), "Shipping #AI features for #SaaS teams today"
    )

    assert post["status"] == "draft"
    assert post["is_editable"] is True
    assert post["character_count"] == len("Shipping #AI features for #SaaS teams today")
    assert post["word_count"] == 7
    assert post["hashtags"] == ["AI", "SaaS"]
    assert post["account"]["full_name"] == "Tushar Anand"
    assert post["created_by_name"] == "Owner Person"
    # Nothing is scheduled by creating a draft.
    assert post["scheduled_at"] is None


async def test_autosave_patch_updates_content(client: AsyncClient, db: AsyncSession) -> None:
    token, ws = await register(client)
    account = await make_account(db, ws)
    post = await create_draft(client, token, ws, str(account.id))

    response = await client.patch(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}",
        json={"content": "Draft saved while typing"},
        headers=auth(token),
    )

    assert response.status_code == 200, response.text
    assert response.json()["content"] == "Draft saved while typing"

    # And it survives a reload, which is the whole point of autosave.
    reloaded = await client.get(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}", headers=auth(token)
    )
    assert reloaded.json()["content"] == "Draft saved while typing"


async def test_delete_draft(client: AsyncClient, db: AsyncSession) -> None:
    token, ws = await register(client)
    account = await make_account(db, ws)
    post = await create_draft(client, token, ws, str(account.id))

    response = await client.delete(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}", headers=auth(token)
    )
    assert response.status_code == 204

    missing = await client.get(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}", headers=auth(token)
    )
    assert missing.status_code == 404


async def test_duplicate_creates_a_new_draft(client: AsyncClient, db: AsyncSession) -> None:
    token, ws = await register(client)
    account = await make_account(db, ws)
    post = await create_draft(client, token, ws, str(account.id), "Original copy")

    response = await client.post(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}/duplicate", headers=auth(token)
    )

    assert response.status_code == 201, response.text
    copy = response.json()
    assert copy["id"] != post["id"]
    assert copy["content"] == "Original copy"
    # A duplicate is never inherited as scheduled or published.
    assert copy["status"] == "draft"


# ── media ────────────────────────────────────────────────────────────────────

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d494844520000000100000001080600000"
    "01f15c4890000000a49444154789c6300010000050001"
    "0d0a2db40000000049454e44ae426082"
)


async def test_upload_image_and_attach_to_post(
    client: AsyncClient, db: AsyncSession, storage: dict[str, bytes]
) -> None:
    token, ws = await register(client)
    account = await make_account(db, ws)

    upload = await client.post(
        f"/api/v1/workspaces/{ws}/content/media",
        files={"file": ("shot.png", PNG_1PX, "image/png")},
        headers=auth(token),
    )
    assert upload.status_code == 201, upload.text
    asset = upload.json()
    assert asset["kind"] == "image"
    assert asset["size_bytes"] == len(PNG_1PX)
    assert asset["width"] == 1 and asset["height"] == 1
    assert asset["url"].startswith("https://signed/")
    # Stored under a tenant-prefixed key, never at the bucket root.
    assert any(key.startswith(f"workspaces/{ws}/media/") for key in storage)

    post = await create_draft(client, token, ws, str(account.id))
    attached = await client.patch(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}",
        json={"media": [{"media_asset_id": asset["id"], "alt_text": "A screenshot"}]},
        headers=auth(token),
    )
    assert attached.status_code == 200, attached.text
    media = attached.json()["media"]
    assert len(media) == 1
    assert media[0]["alt_text"] == "A screenshot"
    assert media[0]["asset"]["id"] == asset["id"]


async def test_upload_rejects_unsupported_type(client: AsyncClient, storage: dict[str, bytes]) -> None:
    token, ws = await register(client)

    response = await client.post(
        f"/api/v1/workspaces/{ws}/content/media",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers=auth(token),
    )

    assert response.status_code == 422
    assert "not a file type LinkedIn accepts" in response.json()["error"]["message"]


async def test_media_from_another_workspace_is_refused(
    client: AsyncClient, db: AsyncSession, storage: dict[str, bytes]
) -> None:
    """Workspace isolation on attachments, not just on posts."""
    token_a, ws_a = await register(client, "a@example.com", "Alpha")
    token_b, ws_b = await register(client, "b@example.com", "Beta")
    account_b = await make_account(db, ws_b)

    upload = await client.post(
        f"/api/v1/workspaces/{ws_a}/content/media",
        files={"file": ("shot.png", PNG_1PX, "image/png")},
        headers=auth(token_a),
    )
    foreign_asset = upload.json()["id"]

    post = await create_draft(client, token_b, ws_b, str(account_b.id))
    response = await client.patch(
        f"/api/v1/workspaces/{ws_b}/content/posts/{post['id']}",
        json={"media": [{"media_asset_id": foreign_asset}]},
        headers=auth(token_b),
    )

    assert response.status_code == 404


# ── scheduling ───────────────────────────────────────────────────────────────


async def test_schedule_converts_local_time_to_utc(
    client: AsyncClient, db: AsyncSession, publishing_configured: None
) -> None:
    token, ws = await register(client)
    account = await make_account(db, ws)
    post = await create_draft(client, token, ws, str(account.id))

    future = date.today() + timedelta(days=10)
    response = await client.post(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}/schedule",
        json={
            "scheduled_date": future.isoformat(),
            "scheduled_time": "09:30",
            "timezone": "Asia/Kolkata",
        },
        headers=auth(token),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "scheduled"
    assert body["scheduled_timezone"] == "Asia/Kolkata"
    # 09:30 IST is 04:00 UTC — the stored instant is UTC, the zone is kept beside it.
    stored = datetime.fromisoformat(body["scheduled_at"])
    assert stored.astimezone(UTC).hour == 4
    assert stored.astimezone(UTC).minute == 0


async def test_schedule_in_the_past_is_refused(
    client: AsyncClient, db: AsyncSession, publishing_configured: None
) -> None:
    token, ws = await register(client)
    account = await make_account(db, ws)
    post = await create_draft(client, token, ws, str(account.id))

    past = date.today() - timedelta(days=1)
    response = await client.post(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}/schedule",
        json={"scheduled_date": past.isoformat(), "scheduled_time": "09:30", "timezone": "UTC"},
        headers=auth(token),
    )

    assert response.status_code == 422
    assert "in the past" in response.json()["error"]["message"]


async def test_reschedule_replaces_the_slot_without_leaving_a_second_one(
    client: AsyncClient, db: AsyncSession, publishing_configured: None, sent_tasks: list[dict[str, Any]]
) -> None:
    """Rescheduling is an UPDATE: there is no job to cancel, and none is created."""
    token, ws = await register(client)
    account = await make_account(db, ws)
    post = await create_draft(client, token, ws, str(account.id))
    url = f"/api/v1/workspaces/{ws}/content/posts/{post['id']}/schedule"

    first = date.today() + timedelta(days=3)
    second = date.today() + timedelta(days=5)
    await client.post(
        url,
        json={"scheduled_date": first.isoformat(), "scheduled_time": "10:00", "timezone": "UTC"},
        headers=auth(token),
    )
    response = await client.post(
        url,
        json={"scheduled_date": second.isoformat(), "scheduled_time": "16:45", "timezone": "UTC"},
        headers=auth(token),
    )

    assert response.status_code == 200
    stored = datetime.fromisoformat(response.json()["scheduled_at"]).astimezone(UTC)
    assert stored.date() == second
    assert stored.hour == 16
    # Scheduling never enqueues anything; the Beat sweep is the only dispatcher.
    assert sent_tasks == []


async def test_cancel_scheduled_post(
    client: AsyncClient, db: AsyncSession, publishing_configured: None
) -> None:
    token, ws = await register(client)
    account = await make_account(db, ws)
    post = await create_draft(client, token, ws, str(account.id))

    future = date.today() + timedelta(days=2)
    await client.post(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}/schedule",
        json={"scheduled_date": future.isoformat(), "scheduled_time": "09:00", "timezone": "UTC"},
        headers=auth(token),
    )
    response = await client.post(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}/cancel", headers=auth(token)
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["scheduled_at"] is None


async def test_empty_post_cannot_be_scheduled(
    client: AsyncClient, db: AsyncSession, publishing_configured: None
) -> None:
    token, ws = await register(client)
    account = await make_account(db, ws)
    post = await create_draft(client, token, ws, str(account.id), "")

    future = date.today() + timedelta(days=1)
    response = await client.post(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}/schedule",
        json={"scheduled_date": future.isoformat(), "scheduled_time": "09:00", "timezone": "UTC"},
        headers=auth(token),
    )

    assert response.status_code == 422
    assert "needs text or media" in response.json()["error"]["message"]


# ── publishing capability ────────────────────────────────────────────────────


async def test_publish_now_enqueues_the_worker(
    client: AsyncClient,
    db: AsyncSession,
    publishing_configured: None,
    sent_tasks: list[dict[str, Any]],
) -> None:
    token, ws = await register(client)
    account = await make_account(db, ws)
    post = await create_draft(client, token, ws, str(account.id))

    response = await client.post(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}/publish", headers=auth(token)
    )

    assert response.status_code == 200, response.text
    # The API never declares a post published; only the worker may do that.
    assert response.json()["status"] == "scheduled"
    assert len(sent_tasks) == 1
    assert sent_tasks[0]["name"] == "content.publish_post"
    assert sent_tasks[0]["args"] == [post["id"]]


async def test_publishing_without_a_grant_reports_the_missing_capability(
    client: AsyncClient, db: AsyncSession, publishing_configured: None
) -> None:
    """The product must say the permission is missing, never pretend to publish."""
    token, ws = await register(client)
    account = await make_account(db, ws, granted=False)
    post = await create_draft(client, token, ws, str(account.id))

    response = await client.post(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}/publish", headers=auth(token)
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["details"]["code"] == "not_authorized"
    assert error["details"]["remedy"] == "authorize"

    unchanged = await client.get(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}", headers=auth(token)
    )
    assert unchanged.json()["status"] == "draft"


async def test_publishing_unconfigured_deployment_reports_configuration(
    client: AsyncClient, db: AsyncSession
) -> None:
    token, ws = await register(client)
    account = await make_account(db, ws)
    post = await create_draft(client, token, ws, str(account.id))

    response = await client.post(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}/publish", headers=auth(token)
    )

    assert response.status_code == 409
    assert response.json()["error"]["details"]["code"] == "not_configured"


async def test_account_response_exposes_capability_but_never_a_token(
    client: AsyncClient, db: AsyncSession, publishing_configured: None
) -> None:
    token, ws = await register(client)
    await make_account(db, ws)

    response = await client.get(f"/api/v1/workspaces/{ws}/linkedin-accounts", headers=auth(token))

    account = response.json()[0]
    assert account["publishing"]["available"] is True
    assert account["publishing"]["code"] == "ready"
    assert POST_SCOPE in account["publishing"]["scopes"]
    # No credential, in any shape, anywhere in the payload.
    serialized = response.text
    assert "a-member-token" not in serialized
    assert "ciphertext" not in serialized


async def test_authorize_url_requires_a_configured_app(
    client: AsyncClient, db: AsyncSession
) -> None:
    token, ws = await register(client)
    account = await make_account(db, ws, granted=False)

    response = await client.post(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/{account.id}/publishing/authorize",
        headers=auth(token),
    )

    assert response.status_code == 409
    assert "no LinkedIn app configured" in response.json()["error"]["message"]


async def test_authorize_url_is_linkedin_consent_with_signed_state(
    client: AsyncClient, db: AsyncSession, publishing_configured: None
) -> None:
    from app.linkedin import publishing

    token, ws = await register(client)
    account = await make_account(db, ws, granted=False)

    response = await client.post(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/{account.id}/publishing/authorize",
        headers=auth(token),
    )

    assert response.status_code == 200, response.text
    url = response.json()["authorize_url"]
    assert url.startswith("https://www.linkedin.com/oauth/v2/authorization?")
    assert "w_member_social" in url

    state = url.split("state=")[1].split("&")[0]
    parsed = publishing.decode_state(state)
    assert parsed.account_id == account.id
    assert parsed.workspace_id == uuid.UUID(ws)


async def test_oauth_callback_rejects_a_forged_state(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/linkedin/oauth/callback?code=abc&state=not-a-real-state",
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert "publishing=error" in response.headers["location"]


# ── analytics honesty ────────────────────────────────────────────────────────


async def test_analytics_are_reported_unavailable_not_zeroed(
    client: AsyncClient, db: AsyncSession, publishing_configured: None
) -> None:
    from app.models.content import LinkedInPost, PostStatus

    token, ws = await register(client)
    account = await make_account(db, ws)
    post = await create_draft(client, token, ws, str(account.id))

    row = await db.get(LinkedInPost, uuid.UUID(post["id"]))
    assert row is not None
    row.status = PostStatus.PUBLISHED
    row.published_at = datetime.now(UTC)
    row.linkedin_post_id = "urn:li:share:123"
    await db.flush()

    response = await client.get(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}", headers=auth(token)
    )

    analytics = response.json()["analytics"]
    assert analytics["available"] is False
    assert "r_member_social" in analytics["message"]
    # Crucially: no fabricated zeros.
    assert analytics["impressions"] is None
    assert analytics["likes"] is None


# ── authorization and isolation ──────────────────────────────────────────────


async def test_workspace_isolation_on_posts(client: AsyncClient, db: AsyncSession) -> None:
    token_a, ws_a = await register(client, "a@example.com", "Alpha")
    token_b, ws_b = await register(client, "b@example.com", "Beta")
    account_a = await make_account(db, ws_a)
    post = await create_draft(client, token_a, ws_a, str(account_a.id), "Alpha's private draft")

    # Another tenant's workspace does not even exist as far as B is concerned.
    via_a = await client.get(
        f"/api/v1/workspaces/{ws_a}/content/posts/{post['id']}", headers=auth(token_b)
    )
    assert via_a.status_code == 404

    # And the post is not reachable by re-parenting the path onto B's workspace.
    via_b = await client.get(
        f"/api/v1/workspaces/{ws_b}/content/posts/{post['id']}", headers=auth(token_b)
    )
    assert via_b.status_code == 404

    listing = await client.get(
        f"/api/v1/workspaces/{ws_b}/content/posts", headers=auth(token_b)
    )
    assert listing.json()["items"] == []


async def test_post_cannot_be_bound_to_another_workspaces_account(
    client: AsyncClient, db: AsyncSession
) -> None:
    token_a, ws_a = await register(client, "a@example.com", "Alpha")
    _, ws_b = await register(client, "b@example.com", "Beta")
    account_b = await make_account(db, ws_b)

    response = await client.post(
        f"/api/v1/workspaces/{ws_a}/content/posts",
        json={"linkedin_account_id": str(account_b.id), "content": "hi"},
        headers=auth(token_a),
    )

    assert response.status_code == 404


async def add_member(
    db: AsyncSession, client: AsyncClient, workspace_id: str, email: str
) -> str:
    """Signs a second user up and joins them to an existing workspace as member."""
    signup = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": "correct horse 7",
            "full_name": "Team Member",
            "workspace_name": "Their Own",
        },
    )
    token = signup.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers=auth(token))
    user_id = me.json()["user"]["id"]

    db.add(
        WorkspaceMember(
            workspace_id=uuid.UUID(workspace_id),
            user_id=uuid.UUID(user_id),
            role=WorkspaceRole.MEMBER,
        )
    )
    await db.flush()
    return token


async def test_member_can_draft_but_not_publish(
    client: AsyncClient, db: AsyncSession, publishing_configured: None
) -> None:
    owner_token, ws = await register(client)
    account = await make_account(db, ws)
    member_token = await add_member(db, client, ws, "member@example.com")

    post = await create_draft(client, member_token, ws, str(account.id), "Member's draft")
    assert post["status"] == "draft"

    publish = await client.post(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}/publish", headers=auth(member_token)
    )
    assert publish.status_code == 403
    assert "admin role" in publish.json()["error"]["message"]

    future = date.today() + timedelta(days=1)
    schedule = await client.post(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}/schedule",
        json={"scheduled_date": future.isoformat(), "scheduled_time": "09:00", "timezone": "UTC"},
        headers=auth(member_token),
    )
    assert schedule.status_code == 403

    # The owner can, on the same post.
    ok = await client.post(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}/schedule",
        json={"scheduled_date": future.isoformat(), "scheduled_time": "09:00", "timezone": "UTC"},
        headers=auth(owner_token),
    )
    assert ok.status_code == 200


async def test_member_cannot_edit_someone_elses_draft(
    client: AsyncClient, db: AsyncSession
) -> None:
    owner_token, ws = await register(client)
    account = await make_account(db, ws)
    member_token = await add_member(db, client, ws, "member@example.com")
    owners_post = await create_draft(client, owner_token, ws, str(account.id), "Owner's draft")

    response = await client.patch(
        f"/api/v1/workspaces/{ws}/content/posts/{owners_post['id']}",
        json={"content": "hijacked"},
        headers=auth(member_token),
    )

    assert response.status_code == 403


# ── approval workflow ────────────────────────────────────────────────────────


async def test_approval_workflow_is_off_by_default_and_configurable(
    client: AsyncClient, db: AsyncSession, publishing_configured: None
) -> None:
    token, ws = await register(client)
    account = await make_account(db, ws)

    settings_response = await client.get(
        f"/api/v1/workspaces/{ws}/content/settings/approval", headers=auth(token)
    )
    assert settings_response.json() == {"approval_required": False, "can_approve": True}

    await client.put(
        f"/api/v1/workspaces/{ws}/content/settings/approval",
        json={"approval_required": True},
        headers=auth(token),
    )

    post = await create_draft(client, token, ws, str(account.id))
    future = date.today() + timedelta(days=1)
    blocked = await client.post(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}/schedule",
        json={"scheduled_date": future.isoformat(), "scheduled_time": "09:00", "timezone": "UTC"},
        headers=auth(token),
    )
    assert blocked.status_code == 409
    assert "approved" in blocked.json()["error"]["message"]

    await client.post(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}/submit", headers=auth(token)
    )
    approved = await client.post(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}/approve",
        json={"note": "Looks good"},
        headers=auth(token),
    )
    assert approved.json()["status"] == "approved"

    now_allowed = await client.post(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}/schedule",
        json={"scheduled_date": future.isoformat(), "scheduled_time": "09:00", "timezone": "UTC"},
        headers=auth(token),
    )
    assert now_allowed.status_code == 200


# ── templates, calendar, queue ───────────────────────────────────────────────


async def test_template_crud(client: AsyncClient) -> None:
    token, ws = await register(client)
    base = f"/api/v1/workspaces/{ws}/content/templates"

    created = await client.post(
        base, json={"name": "Launch announcement", "content": "We shipped {thing}"},
        headers=auth(token),
    )
    assert created.status_code == 201, created.text
    template_id = created.json()["id"]

    listed = await client.get(base, headers=auth(token))
    assert [t["name"] for t in listed.json()] == ["Launch announcement"]

    updated = await client.patch(
        f"{base}/{template_id}", json={"content": "We just shipped {thing}"}, headers=auth(token)
    )
    assert updated.json()["content"] == "We just shipped {thing}"

    removed = await client.delete(f"{base}/{template_id}", headers=auth(token))
    assert removed.status_code == 204
    assert (await client.get(base, headers=auth(token))).json() == []


async def test_calendar_renders_in_the_requested_timezone(
    client: AsyncClient, db: AsyncSession, publishing_configured: None
) -> None:
    token, ws = await register(client)
    account = await make_account(db, ws)
    post = await create_draft(client, token, ws, str(account.id))

    future = date.today() + timedelta(days=4)
    await client.post(
        f"/api/v1/workspaces/{ws}/content/posts/{post['id']}/schedule",
        json={
            "scheduled_date": future.isoformat(),
            "scheduled_time": "23:30",
            "timezone": "Asia/Kolkata",
        },
        headers=auth(token),
    )

    response = await client.get(
        f"/api/v1/workspaces/{ws}/content/calendar"
        f"?start={date.today().isoformat()}&end={(date.today() + timedelta(days=10)).isoformat()}"
        "&timezone=Asia/Kolkata",
        headers=auth(token),
    )

    entries = response.json()["entries"]
    assert len(entries) == 1
    # 23:30 IST stays on the user's own date, though it is 18:00 UTC.
    assert entries[0]["local_date"] == future.isoformat()
    assert entries[0]["local_time"] == "23:30"


async def test_queue_assigns_slots_in_order(
    client: AsyncClient, db: AsyncSession, publishing_configured: None
) -> None:
    token, ws = await register(client)
    account = await make_account(db, ws)
    first = await create_draft(client, token, ws, str(account.id), "First in line")
    second = await create_draft(client, token, ws, str(account.id), "Second in line")

    for post in (first, second):
        response = await client.post(
            f"/api/v1/workspaces/{ws}/content/posts/{post['id']}/queue",
            json={},
            headers=auth(token),
        )
        assert response.status_code == 200, response.text

    queue = response.json()
    assert [item["content"] for item in queue["items"]] == ["First in line", "Second in line"]
    assert [item["queue_position"] for item in queue["items"]] == [0, 1]
    times = [datetime.fromisoformat(item["scheduled_at"]) for item in queue["items"]]
    assert times[0] < times[1]

    moved = await client.post(
        f"/api/v1/workspaces/{ws}/content/posts/{second['id']}/queue/move",
        json={"direction": "up"},
        headers=auth(token),
    )
    assert [item["content"] for item in moved.json()["items"]] == [
        "Second in line",
        "First in line",
    ]


async def test_list_filters_by_status_and_search(
    client: AsyncClient, db: AsyncSession, publishing_configured: None
) -> None:
    token, ws = await register(client)
    account = await make_account(db, ws)
    await create_draft(client, token, ws, str(account.id), "Thoughts on hiring")
    scheduled = await create_draft(client, token, ws, str(account.id), "Product launch next week")

    future = date.today() + timedelta(days=6)
    await client.post(
        f"/api/v1/workspaces/{ws}/content/posts/{scheduled['id']}/schedule",
        json={"scheduled_date": future.isoformat(), "scheduled_time": "09:00", "timezone": "UTC"},
        headers=auth(token),
    )

    only_scheduled = await client.get(
        f"/api/v1/workspaces/{ws}/content/posts?status=scheduled", headers=auth(token)
    )
    assert [p["content"] for p in only_scheduled.json()["items"]] == ["Product launch next week"]
    assert only_scheduled.json()["counts"]["draft"] == 1
    assert only_scheduled.json()["counts"]["scheduled"] == 1

    searched = await client.get(
        f"/api/v1/workspaces/{ws}/content/posts?search=hiring", headers=auth(token)
    )
    assert [p["content"] for p in searched.json()["items"]] == ["Thoughts on hiring"]
