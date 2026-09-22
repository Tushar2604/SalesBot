"""Auth flow: signup, login, token rotation, refresh-reuse revocation."""

from __future__ import annotations

from httpx import AsyncClient

from app.api.routes_auth import _COOKIE_PATH as COOKIE_PATH
from app.api.routes_auth import REFRESH_COOKIE


async def _signup(client: AsyncClient, payload: dict[str, str]) -> str:
    response = await client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code == 201, response.text
    return str(response.json()["access_token"])


async def test_signup_creates_user_workspace_and_tokens(
    client: AsyncClient, signup_payload: dict[str, str]
) -> None:
    response = await client.post("/api/v1/auth/signup", json=signup_payload)

    assert response.status_code == 201
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0
    # The refresh token must never appear in the response body.
    assert "refresh_token" not in body
    assert REFRESH_COOKIE in response.cookies

    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert me.status_code == 200
    data = me.json()
    assert data["user"]["email"] == signup_payload["email"]
    assert len(data["workspaces"]) == 1
    assert data["workspaces"][0]["role"] == "owner"
    assert data["workspaces"][0]["workspace"]["name"] == "Acme Outbound"


async def test_signup_rejects_duplicate_email(
    client: AsyncClient, signup_payload: dict[str, str]
) -> None:
    await _signup(client, signup_payload)
    again = await client.post("/api/v1/auth/signup", json=signup_payload)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "conflict"


async def test_signup_rejects_weak_password(
    client: AsyncClient, signup_payload: dict[str, str]
) -> None:
    response = await client.post(
        "/api/v1/auth/signup", json={**signup_payload, "password": "short1"}
    )
    assert response.status_code == 422


async def test_login_succeeds_and_wrong_password_is_indistinguishable(
    client: AsyncClient, signup_payload: dict[str, str]
) -> None:
    await _signup(client, signup_payload)

    good = await client.post(
        "/api/v1/auth/login",
        json={"email": signup_payload["email"], "password": signup_payload["password"]},
    )
    assert good.status_code == 200

    wrong_password = await client.post(
        "/api/v1/auth/login",
        json={"email": signup_payload["email"], "password": "wrong password 1"},
    )
    unknown_email = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "wrong password 1"},
    )

    # No account enumeration: identical status and message for both failures.
    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


async def test_me_requires_a_token(client: AsyncClient) -> None:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


async def test_refresh_rotates_and_reuse_revokes_every_session(
    client: AsyncClient, signup_payload: dict[str, str]
) -> None:
    signup = await client.post("/api/v1/auth/signup", json=signup_payload)
    original_refresh = signup.cookies[REFRESH_COOKIE]

    first = await client.post("/api/v1/auth/refresh")
    assert first.status_code == 200
    rotated_refresh = first.cookies[REFRESH_COOKIE]
    assert rotated_refresh != original_refresh

    # Replaying the consumed token is treated as theft.
    client.cookies.set(REFRESH_COOKIE, original_refresh, path=COOKIE_PATH)
    replay = await client.post("/api/v1/auth/refresh")
    assert replay.status_code == 401

    # ...and the whole family is revoked, so the rotated token is dead too.
    client.cookies.set(REFRESH_COOKIE, rotated_refresh, path=COOKIE_PATH)
    after_breach = await client.post("/api/v1/auth/refresh")
    assert after_breach.status_code == 401


async def test_logout_revokes_the_session(
    client: AsyncClient, signup_payload: dict[str, str]
) -> None:
    await client.post("/api/v1/auth/signup", json=signup_payload)

    logout = await client.post("/api/v1/auth/logout")
    assert logout.status_code == 204

    refresh = await client.post("/api/v1/auth/refresh")
    assert refresh.status_code == 401


async def test_logout_without_a_session_is_idempotent(client: AsyncClient) -> None:
    assert (await client.post("/api/v1/auth/logout")).status_code == 204
