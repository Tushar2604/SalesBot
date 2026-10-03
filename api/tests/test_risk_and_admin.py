"""The ban-risk policy, the warning (strike) system, and the platform admin panel."""

from __future__ import annotations

import uuid
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import assistant as ai
from app.linkedin import health, risk
from app.linkedin.classify import Classification, ResponseClass
from app.models.linkedin import AccountRiskEvent, LinkedInAccount, LinkedInAccountStatus
from app.models.tenancy import User


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


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def make_account(db: AsyncSession, workspace_id: str) -> LinkedInAccount:
    from app.core.crypto import encrypt_str

    account = LinkedInAccount(
        workspace_id=uuid.UUID(workspace_id),
        label="Recruiter",
        full_name="Priya Recruiter",
        public_id="priya",
        profile_urn="urn:li:fsd_profile:PRIYA",
        status=LinkedInAccountStatus.ACTIVE,
        session_ciphertext=encrypt_str("session"),
        proxy=None,
    )
    db.add(account)
    await db.flush()
    return account


async def make_superuser(db: AsyncSession, email: str) -> None:
    await db.execute(update(User).where(User.email == email).values(is_superuser=True))
    await db.flush()


# ── the policy itself ────────────────────────────────────────────────────────


def test_safe_values_raise_no_risks() -> None:
    assert risk.caps_risks(
        {"daily_invites": 20, "daily_messages": 30, "weekdays_only": True,
         "working_hours": {"start": "09:00", "end": "17:30"}},
        test_mode=None,
        account_age_days=30,
    ) == []
    assert risk.step_risks([{"timing": "smart"}, {"timing": "delay", "delay_minutes": 120}]) == []
    assert risk.assistant_risks({"mode": "auto", "reply_delay_min_minutes": 3,
                                 "working_hours_only": True,
                                 "max_replies_per_thread_per_day": 3,
                                 "max_replies_per_account_per_day": 20}) == []


def test_draft_mode_is_never_risky() -> None:
    # A person approves every draft, so fast settings cannot reach LinkedIn on their own.
    assert risk.assistant_risks({"mode": "draft", "reply_delay_min_minutes": 1,
                                 "working_hours_only": False}) == []


def test_risk_levels() -> None:
    assert [risk.risk_level(n) for n in (0, 1, 2, 3, 5)] == [
        "safe", "watch", "at_risk", "critical", "critical"
    ]


# ── strikes from LinkedIn ────────────────────────────────────────────────────


def test_three_linkedin_strikes_pause_the_account(sdb: Any) -> None:
    from app.models.tenancy import Workspace

    workspace = Workspace(name="W", slug=f"w-{uuid.uuid4().hex[:8]}")
    sdb.add(workspace)
    sdb.flush()
    account = LinkedInAccount(
        workspace_id=workspace.id, label="A", status=LinkedInAccountStatus.ACTIVE, proxy=None
    )
    sdb.add(account)
    sdb.flush()

    soft = Classification(ResponseClass.SOFT_LIMIT, detail="weekly limit")
    health.apply_classification(account, soft)
    health.apply_classification(account, soft)
    assert account.status is LinkedInAccountStatus.ACTIVE
    assert risk.strikes_sync(sdb, account.id) == 2

    health.apply_classification(account, soft)
    assert risk.strikes_sync(sdb, account.id) == 3
    assert account.status is LinkedInAccountStatus.PAUSED
    assert "3 safety warnings" in account.status_detail


def test_ok_responses_add_no_strikes(sdb: Any) -> None:
    from app.models.tenancy import Workspace

    workspace = Workspace(name="W", slug=f"w-{uuid.uuid4().hex[:8]}")
    sdb.add(workspace)
    sdb.flush()
    account = LinkedInAccount(
        workspace_id=workspace.id, label="A", status=LinkedInAccountStatus.ACTIVE, proxy=None
    )
    sdb.add(account)
    sdb.flush()
    health.apply_classification(account, Classification(ResponseClass.OK))
    assert risk.strikes_sync(sdb, account.id) == 0


# ── overrides through the API ────────────────────────────────────────────────


async def test_risky_assistant_settings_need_acknowledgement(
    client: AsyncClient, db: AsyncSession
) -> None:
    token, ws = await register(client)
    account = await make_account(db, ws)
    url = f"/api/v1/workspaces/{ws}/assistant/settings"
    risky = {"mode": "auto", "reply_delay_min_minutes": 1, "working_hours_only": False}

    refused = await client.put(url, json=risky, headers=auth(token))
    assert refused.status_code == 409
    keys = {r["key"] for r in refused.json()["error"]["details"]["risks"]}
    assert keys == {"reply_delay", "reply_after_hours"}
    # Nothing was saved.
    assert (await client.get(url, headers=auth(token))).json()["mode"] == "off"

    accepted = await client.put(url, json={**risky, "acknowledge_risk": True}, headers=auth(token))
    assert accepted.status_code == 200
    events = (await db.execute(
        select(AccountRiskEvent).where(AccountRiskEvent.linkedin_account_id == account.id)
    )).scalars().all()
    assert len(events) == 1 and events[0].source == "override"

    # Re-saving the already-accepted settings does not warn or strike again.
    again = await client.put(url, json=risky, headers=auth(token))
    assert again.status_code == 200


async def test_resuming_a_flagged_account_needs_acknowledgement(
    client: AsyncClient, db: AsyncSession
) -> None:
    token, ws = await register(client)
    account = await make_account(db, ws)
    account.status = LinkedInAccountStatus.PAUSED
    for _ in range(3):
        db.add(AccountRiskEvent(
            linkedin_account_id=account.id, workspace_id=account.workspace_id,
            source="linkedin", kind="soft_limit", strikes=1, detail="x",
        ))
    await db.flush()
    url = f"/api/v1/workspaces/{ws}/linkedin-accounts/{account.id}/pause?paused=false"

    refused = await client.post(url, headers=auth(token))
    assert refused.status_code == 409
    assert refused.json()["error"]["details"]["risks"][0]["key"] == "resume_flagged"

    resumed = await client.post(f"{url}&acknowledge_risk=true", headers=auth(token))
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "active"
    assert resumed.json()["warning_count"] == 4


# ── the admin panel ──────────────────────────────────────────────────────────


async def test_admin_panel_is_superuser_only(client: AsyncClient, db: AsyncSession) -> None:
    token, _ = await register(client)
    response = await client.get("/api/v1/admin/linkedin-accounts", headers=auth(token))
    assert response.status_code == 403


async def test_admin_sees_who_runs_each_account_and_its_warnings(
    client: AsyncClient, db: AsyncSession
) -> None:
    token, ws = await register(client, "boss@example.com")
    await make_superuser(db, "boss@example.com")
    account = await make_account(db, ws)
    db.add(AccountRiskEvent(
        linkedin_account_id=account.id, workspace_id=account.workspace_id,
        source="linkedin", kind="challenge", strikes=2, detail="security check",
    ))
    await db.flush()

    rows = (await client.get("/api/v1/admin/linkedin-accounts", headers=auth(token))).json()
    row = next(r for r in rows if r["id"] == str(account.id))
    assert row["workspace_name"] == "Acme"
    assert row["members"][0]["email"] == "boss@example.com"
    assert row["warning_count"] == 2
    assert row["risk_level"] == "at_risk"
    assert row["last_warning"] == "security check"

    events = (await client.get(
        f"/api/v1/admin/linkedin-accounts/{account.id}/events", headers=auth(token)
    )).json()
    cleared = await client.post(f"/api/v1/admin/risk-events/{events[0]['id']}/clear", headers=auth(token))
    assert cleared.status_code == 200
    rows = (await client.get("/api/v1/admin/linkedin-accounts", headers=auth(token))).json()
    assert next(r for r in rows if r["id"] == str(account.id))["warning_count"] == 0


async def test_revoked_account_cannot_be_reconnected_until_restored(
    client: AsyncClient, db: AsyncSession
) -> None:
    token, ws = await register(client, "boss@example.com")
    await make_superuser(db, "boss@example.com")
    account = await make_account(db, ws)

    revoked = await client.post(
        f"/api/v1/admin/linkedin-accounts/{account.id}/revoke",
        json={"reason": "too many warnings"},
        headers=auth(token),
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "disabled"
    await db.refresh(account)
    assert account.session_ciphertext is None

    reconnect = await client.post(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/connect/cookie",
        json={"li_at": "AQEDA" + "x" * 30, "account_id": str(account.id)},
        headers=auth(token),
    )
    assert reconnect.status_code == 403

    restored = await client.post(
        f"/api/v1/admin/linkedin-accounts/{account.id}/restore", json={}, headers=auth(token)
    )
    assert restored.json()["status"] == "disconnected"


# ── the assistant's context ──────────────────────────────────────────────────


def test_assistant_asks_only_for_what_is_still_missing() -> None:
    config = ai.AssistantConfig("", "", "", ("notice period", "current CTC", "email"))
    known = {"notice_period": "30 days", "email": ""}
    assert ai.still_to_collect(config.collect_fields, known) == ["current CTC", "email"]

    text = ai._transcript(
        [ai.Turn(False, "sure, what do you need?")],
        "Ravi",
        config=config,
        known_facts=known,
        recent_openers=["ah got it, thanks"],
    )
    assert "<still_to_find_out>\n- current CTC\n- email\n</still_to_find_out>" in text
    assert "- notice_period: 30 days" in text
    assert "ah got it, thanks" in text


def test_assistant_never_claims_to_be_human() -> None:
    assert "never deny it" in ai._RULES
    assert "Never say or imply you are an AI" not in ai._RULES


# ── background reading follows the account's day ─────────────────────────────


def test_background_reading_sleeps_at_night_and_slows_off_hours() -> None:
    from datetime import UTC, datetime

    from app.linkedin import caps as caps_mod

    account = LinkedInAccount(timezone="Asia/Kolkata", caps={}, test_mode=False)
    # Thursday 2026-09-24; Kolkata is UTC+5:30.
    at = lambda hh, mm: datetime(2026, 9, 24, hh, mm, tzinfo=UTC)  # noqa: E731
    assert caps_mod.background_cadence(account, now=at(6, 0)) == "active"  # 11:30 local
    assert caps_mod.background_cadence(account, now=at(14, 30)) == "light"  # 20:00 local
    assert caps_mod.background_cadence(account, now=at(20, 30)) == "asleep"  # 02:00 local


# ── proxies are measured, not trusted ────────────────────────────────────────


async def _add_proxy(client: AsyncClient, token: str, ws: str, **extra: Any) -> Any:
    return await client.post(
        f"/api/v1/workspaces/{ws}/proxies",
        json={"host": "82.41.252.236", "port": 43291, "country": "IN", **extra},
        headers=auth(token),
    )


async def test_a_proxy_that_cannot_connect_is_refused(client: AsyncClient, monkeypatch: Any) -> None:
    from app.linkedin import proxy as proxy_mod

    async def dead(url: str) -> proxy_mod.ExitProbe:
        return proxy_mod.ExitProbe(ok=False, error="ProxyError")

    monkeypatch.setattr(proxy_mod, "probe_exit", dead)
    token, ws = await register(client)
    response = await _add_proxy(client, token, ws)
    assert response.status_code == 422
    assert "scheme" in response.json()["error"]["message"]


async def test_a_proxy_exiting_in_another_country_needs_confirmation(
    client: AsyncClient, monkeypatch: Any
) -> None:
    from app.linkedin import proxy as proxy_mod

    async def singapore(url: str) -> proxy_mod.ExitProbe:
        return proxy_mod.ExitProbe(
            ok=True, ip="82.41.252.236", country="SG", city="Singapore", org="AS1 Some ISP"
        )

    monkeypatch.setattr(proxy_mod, "probe_exit", singapore)
    token, ws = await register(client)

    refused = await _add_proxy(client, token, ws)
    assert refused.status_code == 409
    assert refused.json()["error"]["details"]["risks"][0]["key"] == "proxy_country_mismatch"

    accepted = await _add_proxy(client, token, ws, acknowledge_risk=True)
    assert accepted.status_code == 201
    assert accepted.json()["exit_country"] == "SG"
    assert accepted.json()["last_exit_ip"] == "82.41.252.236"


async def test_a_datacenter_proxy_needs_confirmation(client: AsyncClient, monkeypatch: Any) -> None:
    from app.linkedin import proxy as proxy_mod

    async def aws(url: str) -> proxy_mod.ExitProbe:
        return proxy_mod.ExitProbe(ok=True, ip="3.3.3.3", country="IN", org="AS16509 Amazon.com")

    monkeypatch.setattr(proxy_mod, "probe_exit", aws)
    token, ws = await register(client)
    refused = await _add_proxy(client, token, ws)
    assert refused.status_code == 409
    assert refused.json()["error"]["details"]["risks"][0]["key"] == "proxy_datacenter"


# ── one saved browser profile per account ────────────────────────────────────


def test_profile_is_per_account_unlocked_on_launch_and_wiped(
    tmp_path: Any, monkeypatch: Any
) -> None:
    from app.config import settings
    from app.linkedin import browser_profile

    monkeypatch.setattr(settings, "browser_profiles_dir", str(tmp_path))
    account_id = uuid.uuid4()

    directory = browser_profile.prepare(account_id)
    assert directory == str(tmp_path / str(account_id))
    # A lock left by a crash, or by the other container, must not block launch.
    (tmp_path / str(account_id) / "SingletonLock").write_text("other-host-123")
    (tmp_path / str(account_id) / "Default").mkdir()
    browser_profile.prepare(account_id)
    assert not (tmp_path / str(account_id) / "SingletonLock").exists()
    assert (tmp_path / str(account_id) / "Default").exists()  # the profile itself is kept

    browser_profile.wipe(account_id)
    assert not (tmp_path / str(account_id)).exists()


def test_the_driver_runs_in_the_accounts_own_profile() -> None:
    from app.linkedin import build_driver
    from app.linkedin.browser_driver import BrowserDriver
    from app.linkedin.guard import GuardedDriver

    account = LinkedInAccount(id=uuid.uuid4(), fingerprint={}, timezone="UTC", proxy=None)
    driver = build_driver(account, with_session=False)
    # Always handed out wrapped in the action gap guard.
    assert isinstance(driver, GuardedDriver)
    assert isinstance(driver._inner, BrowserDriver)
    assert driver._profile_account_id == account.id


def test_seeded_login_cookies_persist_and_are_not_reseeded_needlessly() -> None:
    import time as _time
    from datetime import UTC, datetime

    from app.linkedin.browser_driver import BrowserDriver
    from app.linkedin.driver import SessionBundle

    class _Context:
        def __init__(self, existing: dict[str, str]) -> None:
            self.existing = existing
            self.added: list[dict[str, Any]] = []

        def cookies(self, url: str) -> list[dict[str, str]]:
            return [{"name": k, "value": v} for k, v in self.existing.items()]

        def add_cookies(self, cookies: list[dict[str, Any]]) -> None:
            self.added.extend(cookies)

    session = SessionBundle(
        cookies={"li_at": "NEW", "JSESSIONID": '"ajax:1"'}, csrf_token="ajax:1",
        established_at=datetime.now(UTC),
    )
    driver = BrowserDriver(fingerprint={}, session=session)

    fresh = _Context({})
    driver._seed_session_cookies(fresh)  # type: ignore[arg-type]
    assert {c["name"] for c in fresh.added} == {"li_at", "JSESSIONID"}
    assert all(c["expires"] > _time.time() + 86400 for c in fresh.added)

    same_login = _Context({"li_at": "NEW", "bcookie": "device-1"})
    driver._seed_session_cookies(same_login)  # type: ignore[arg-type]
    assert same_login.added == []  # the profile's own cookies are left alone


# ── production requires a proxy per account ──────────────────────────────────


async def test_connecting_without_a_proxy_is_refused_when_proxies_are_required(
    client: AsyncClient, monkeypatch: Any
) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "require_proxy", True)
    token, ws = await register(client)
    response = await client.post(
        f"/api/v1/workspaces/{ws}/linkedin-accounts/connect/remote-browser",
        json={"label": "x", "timezone": "Asia/Kolkata"},
        headers=auth(token),
    )
    assert response.status_code == 422
    assert "proxy" in response.json()["error"]["message"]


def test_media_links_are_signed_for_the_public_address(monkeypatch: Any) -> None:
    from app.config import settings
    from app.services import media_service

    monkeypatch.setattr(settings, "s3_public_endpoint_url", "https://files.example.com")
    monkeypatch.setattr(media_service, "_public_client", None)
    url = media_service._presign_sync("workspace/abc.png", 60)
    assert url.startswith("https://files.example.com/")
