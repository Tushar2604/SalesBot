"""Tenant isolation, role enforcement, invites, and the kill switch."""

from __future__ import annotations

from typing import Any

from httpx import AsyncClient


async def _register(client: AsyncClient, email: str, workspace: str) -> tuple[str, str]:
    """Returns (access_token, workspace_id)."""
    signup = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": "correct horse 7",
            "full_name": email.split("@")[0],
            "workspace_name": workspace,
        },
    )
    assert signup.status_code == 201, signup.text
    token = signup.json()["access_token"]

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return token, me.json()["workspaces"][0]["workspace"]["id"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_outsider_cannot_see_another_tenants_workspace(client: AsyncClient) -> None:
    _owner_token, owner_ws = await _register(client, "owner@acme.example.com", "Acme")
    outsider_token, _ = await _register(client, "outsider@other.example.com", "Other Co")

    response = await client.get(f"/api/v1/workspaces/{owner_ws}", headers=_auth(outsider_token))

    # 404, not 403 — an outsider should not learn that the workspace exists.
    assert response.status_code == 404


async def test_invite_flow_creates_member_with_assigned_role(client: AsyncClient) -> None:
    owner_token, workspace_id = await _register(client, "owner@acme.example.com", "Acme")

    invite = await client.post(
        f"/api/v1/workspaces/{workspace_id}/invites",
        json={"email": "rep@acme.example.com", "role": "member"},
        headers=_auth(owner_token),
    )
    assert invite.status_code == 201, invite.text
    invite_url = invite.json()["invite_url"]
    token = invite_url.rsplit("/", 1)[1]

    accepted = await client.post(
        "/api/v1/auth/accept-invite",
        json={"token": token, "password": "another pass 9", "full_name": "Sales Rep"},
    )
    assert accepted.status_code == 200
    rep_token = accepted.json()["access_token"]

    members = await client.get(
        f"/api/v1/workspaces/{workspace_id}/members", headers=_auth(owner_token)
    )
    assert members.status_code == 200
    roles = {m["user"]["email"]: m["role"] for m in members.json()}
    assert roles == {"owner@acme.example.com": "owner", "rep@acme.example.com": "member"}

    # The new member can read the workspace they were invited to.
    assert (
        await client.get(f"/api/v1/workspaces/{workspace_id}", headers=_auth(rep_token))
    ).status_code == 200


async def test_invite_token_cannot_be_reused(client: AsyncClient) -> None:
    owner_token, workspace_id = await _register(client, "owner@acme.example.com", "Acme")
    invite = await client.post(
        f"/api/v1/workspaces/{workspace_id}/invites",
        json={"email": "rep@acme.example.com", "role": "member"},
        headers=_auth(owner_token),
    )
    token = invite.json()["invite_url"].rsplit("/", 1)[1]

    payload: dict[str, Any] = {"token": token, "password": "another pass 9"}
    assert (await client.post("/api/v1/auth/accept-invite", json=payload)).status_code == 200
    second = await client.post("/api/v1/auth/accept-invite", json=payload)
    assert second.status_code == 409


async def test_member_cannot_invite_or_change_settings(client: AsyncClient) -> None:
    owner_token, workspace_id = await _register(client, "owner@acme.example.com", "Acme")
    invite = await client.post(
        f"/api/v1/workspaces/{workspace_id}/invites",
        json={"email": "rep@acme.example.com", "role": "member"},
        headers=_auth(owner_token),
    )
    token = invite.json()["invite_url"].rsplit("/", 1)[1]
    rep_token = (
        await client.post(
            "/api/v1/auth/accept-invite",
            json={"token": token, "password": "another pass 9"},
        )
    ).json()["access_token"]

    forbidden_invite = await client.post(
        f"/api/v1/workspaces/{workspace_id}/invites",
        json={"email": "someone@acme.example.com", "role": "member"},
        headers=_auth(rep_token),
    )
    assert forbidden_invite.status_code == 403

    forbidden_update = await client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        json={"name": "Renamed by a member"},
        headers=_auth(rep_token),
    )
    assert forbidden_update.status_code == 403


async def test_admin_cannot_mint_an_owner(client: AsyncClient) -> None:
    owner_token, workspace_id = await _register(client, "owner@acme.example.com", "Acme")

    admin_invite = await client.post(
        f"/api/v1/workspaces/{workspace_id}/invites",
        json={"email": "admin@acme.example.com", "role": "admin"},
        headers=_auth(owner_token),
    )
    admin_token = (
        await client.post(
            "/api/v1/auth/accept-invite",
            json={
                "token": admin_invite.json()["invite_url"].rsplit("/", 1)[1],
                "password": "another pass 9",
            },
        )
    ).json()["access_token"]

    # Privilege escalation via invite must be blocked, or an admin could seize billing.
    escalation = await client.post(
        f"/api/v1/workspaces/{workspace_id}/invites",
        json={"email": "puppet@acme.example.com", "role": "owner"},
        headers=_auth(admin_token),
    )
    assert escalation.status_code == 403


async def test_last_owner_cannot_be_demoted(client: AsyncClient) -> None:
    owner_token, workspace_id = await _register(client, "owner@acme.example.com", "Acme")
    members = await client.get(
        f"/api/v1/workspaces/{workspace_id}/members", headers=_auth(owner_token)
    )
    owner_member_id = members.json()[0]["id"]

    demote = await client.patch(
        f"/api/v1/workspaces/{workspace_id}/members/{owner_member_id}",
        json={"role": "admin"},
        headers=_auth(owner_token),
    )
    assert demote.status_code == 409


async def test_kill_switch_toggles_and_is_audited(client: AsyncClient) -> None:
    owner_token, workspace_id = await _register(client, "owner@acme.example.com", "Acme")

    paused = await client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        json={"outreach_paused": True},
        headers=_auth(owner_token),
    )
    assert paused.status_code == 200
    assert paused.json()["outreach_paused"] is True

    resumed = await client.patch(
        f"/api/v1/workspaces/{workspace_id}",
        json={"outreach_paused": False},
        headers=_auth(owner_token),
    )
    assert resumed.json()["outreach_paused"] is False


async def test_revoked_invite_cannot_be_accepted(client: AsyncClient) -> None:
    owner_token, workspace_id = await _register(client, "owner@acme.example.com", "Acme")
    invite = await client.post(
        f"/api/v1/workspaces/{workspace_id}/invites",
        json={"email": "rep@acme.example.com", "role": "member"},
        headers=_auth(owner_token),
    )
    invite_id = invite.json()["id"]
    token = invite.json()["invite_url"].rsplit("/", 1)[1]

    revoked = await client.delete(
        f"/api/v1/workspaces/{workspace_id}/invites/{invite_id}", headers=_auth(owner_token)
    )
    assert revoked.status_code == 204

    attempt = await client.post(
        "/api/v1/auth/accept-invite",
        json={"token": token, "password": "another pass 9"},
    )
    assert attempt.status_code == 409
