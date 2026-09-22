"""Connection tracking: what a profile means, and how an invite resolves over time."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from httpx import AsyncClient
from sqlalchemy import select

from app.linkedin.browser_driver import _read_connection_status
from app.linkedin.driver import ConnectionStatus
from app.models.campaigns import CampaignLead, ConnectionState, EnrollmentState
from app.services import tracking
from app.worker.tasks.sync import _resolve_invite
from tests.test_campaigns_api import auth, create_campaign, import_leads, setup_workspace

NOW = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def card(
    text: str = "", buttons: list[str] | None = None, labels: list[str] | None = None
) -> dict[str, Any]:
    return {"text": text, "buttons": buttons or [], "labels": labels or []}


class _NoHistory:
    """Stands in for the session when there is no earlier observation."""

    def __init__(self, previous: str = "") -> None:
        self.previous = previous

    def execute(self, *_: Any, **__: Any) -> Any:
        previous = self.previous

        class _Result:
            def scalar_one_or_none(self) -> Any:
                if not previous:
                    return None

                return SimpleNamespace(meta={"observed": previous})

        return _Result()


def enrollment(days_ago: float = 2, previous_checks: int = 0) -> CampaignLead:
    lead = CampaignLead()
    lead.state = EnrollmentState.COMPLETED
    lead.invite_sent_at = NOW - timedelta(days=days_ago)
    lead.connection_state = ConnectionState.PENDING.value
    lead.check_count = previous_checks
    lead.next_run_at = None
    return lead


# ── reading a profile ────────────────────────────────────────────────────────


def test_first_degree_means_connected() -> None:
    assert (
        _read_connection_status(card("Ana Lee · 1st Engineer", ["Message"]))
        is ConnectionStatus.CONNECTED
    )


def test_pending_button_means_pending() -> None:
    result = _read_connection_status(card("Ana Lee · 2nd", ["Pending", "Follow"]))
    assert result is ConnectionStatus.PENDING


def test_pending_aria_label_means_pending() -> None:
    result = _read_connection_status(
        card("Ana Lee · 2nd", labels=["Pending, click to withdraw invitation"])
    )
    assert result is ConnectionStatus.PENDING


def test_visible_connect_means_not_connected() -> None:
    assert (
        _read_connection_status(card("Ana Lee · 2nd", ["Connect", "Follow"]))
        is ConnectionStatus.NOT_CONNECTED
    )


def test_follow_alone_proves_nothing() -> None:
    assert (
        _read_connection_status(card("Ana Lee · 3rd", ["Follow", "More"]))
        is ConnectionStatus.UNKNOWN
    )


def test_unreadable_page_is_unknown_not_declined() -> None:
    assert _read_connection_status(None) is ConnectionStatus.UNKNOWN


# ── check schedule ───────────────────────────────────────────────────────────


def test_checks_back_off_as_the_invite_ages() -> None:
    fresh = tracking.next_check_delay(timedelta(hours=3))
    middle = tracking.next_check_delay(timedelta(days=2))
    old = tracking.next_check_delay(timedelta(days=10))
    assert fresh < middle < old


# ── resolving an invite ──────────────────────────────────────────────────────


def test_accepted_invite_is_recorded_and_stops_being_checked() -> None:
    lead = enrollment(days_ago=2)
    changed = _resolve_invite(_NoHistory(), lead, ConnectionStatus.CONNECTED, NOW)  # type: ignore[arg-type]
    assert changed == "accepted"
    assert lead.connection_state == ConnectionState.CONNECTED.value
    assert lead.accepted_at == NOW
    assert lead.next_check_at is None


def test_pending_invite_is_rechecked_later() -> None:
    lead = enrollment(days_ago=2)
    changed = _resolve_invite(_NoHistory(), lead, ConnectionStatus.PENDING, NOW)  # type: ignore[arg-type]
    assert changed == ""
    assert lead.connection_state == ConnectionState.PENDING.value
    assert lead.next_check_at is not None and lead.next_check_at > NOW


def test_one_not_pending_sighting_is_not_enough_to_call_it_declined() -> None:
    lead = enrollment(days_ago=2)
    changed = _resolve_invite(_NoHistory(), lead, ConnectionStatus.NOT_CONNECTED, NOW)  # type: ignore[arg-type]
    assert changed == ""
    assert lead.connection_state == ConnectionState.PENDING.value
    # ...and a quick second look is scheduled.
    assert lead.next_check_at is not None and lead.next_check_at - NOW <= timedelta(hours=1)


def test_two_sightings_in_a_row_mark_it_not_accepted() -> None:
    lead = enrollment(days_ago=2)
    changed = _resolve_invite(
        _NoHistory(previous="not_connected"),
        lead,
        ConnectionStatus.NOT_CONNECTED,
        NOW,  # type: ignore[arg-type]
    )
    assert changed == "not_accepted"
    assert lead.connection_state == ConnectionState.NOT_ACCEPTED.value
    assert lead.next_check_at is None


def test_unreadable_page_never_changes_the_outcome() -> None:
    lead = enrollment(days_ago=2)
    changed = _resolve_invite(_NoHistory(), lead, ConnectionStatus.UNKNOWN, NOW)  # type: ignore[arg-type]
    assert changed == ""
    assert lead.connection_state == ConnectionState.PENDING.value
    assert lead.check_count == 0


def test_invite_still_pending_past_the_window_expires() -> None:
    lead = enrollment(days_ago=tracking.tracking_window().days + 1)
    changed = _resolve_invite(_NoHistory(), lead, ConnectionStatus.PENDING, NOW)  # type: ignore[arg-type]
    assert changed == "expired"
    assert lead.connection_state == ConnectionState.EXPIRED.value
    assert lead.next_check_at is None


def test_a_late_acceptance_still_counts_inside_the_window() -> None:
    lead = enrollment(days_ago=tracking.tracking_window().days - 1)
    assert _resolve_invite(_NoHistory(), lead, ConnectionStatus.CONNECTED, NOW) == "accepted"  # type: ignore[arg-type]


# ── HTTP endpoints ───────────────────────────────────────────────────────────


async def _enrolled_campaign(client: AsyncClient, db: Any) -> tuple[str, str, str]:
    token, ws, account_id = await setup_workspace(client, db)
    campaign_id = await create_campaign(client, token, ws, account_id)
    list_id = await import_leads(client, token, ws, count=4)
    enrolled = await client.post(
        f"/api/v1/workspaces/{ws}/campaigns/{campaign_id}/enroll",
        json={"list_id": list_id},
        headers=auth(token),
    )
    assert enrolled.json()["enrolled"] == 4
    return token, ws, campaign_id


async def test_enrolling_starts_every_leads_history(client: AsyncClient, db: Any) -> None:
    token, ws, campaign_id = await _enrolled_campaign(client, db)

    summary = await client.get(
        f"/api/v1/workspaces/{ws}/campaigns/{campaign_id}/tracking", headers=auth(token)
    )
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["total"] == 4
    assert {s["stage"]: s["count"] for s in body["stages"]}["queued"] == 4
    assert sum(s["count"] for s in body["stages"]) == body["total"]

    leads = await client.get(
        f"/api/v1/workspaces/{ws}/campaigns/{campaign_id}/tracking/leads", headers=auth(token)
    )
    assert leads.json()["total"] == 4
    history = await client.get(
        f"/api/v1/workspaces/{ws}/campaigns/{campaign_id}/enrollments/{leads.json()['items'][0]['id']}/events",
        headers=auth(token),
    )
    assert [e["event_type"] for e in history.json()] == ["enrolled"]


async def test_stages_follow_what_happened_to_each_lead(client: AsyncClient, db: Any) -> None:
    token, ws, campaign_id = await _enrolled_campaign(client, db)
    rows = list((await db.execute(select(CampaignLead))).scalars())
    now = datetime.now(UTC)

    rows[0].connection_state = ConnectionState.CONNECTED.value
    rows[0].invite_sent_at = rows[0].accepted_at = now
    rows[1].connection_state = ConnectionState.PENDING.value
    rows[1].invite_sent_at = now - timedelta(days=3)
    rows[2].connection_state = ConnectionState.NOT_ACCEPTED.value
    rows[2].invite_sent_at = now - timedelta(days=5)
    rows[3].replied_at = rows[3].invite_sent_at = rows[3].accepted_at = now
    rows[3].connection_state = ConnectionState.CONNECTED.value
    await db.flush()

    base = f"/api/v1/workspaces/{ws}/campaigns/{campaign_id}/tracking"
    body = (await client.get(base, headers=auth(token))).json()
    counts = {s["stage"]: s["count"] for s in body["stages"]}
    assert counts["connected"] == 1 and counts["invite_pending"] == 1
    assert counts["not_accepted"] == 1 and counts["replied"] == 1
    assert body["invited"] == 4 and body["connected"] == 2 and body["still_waiting"] == 1

    pending = (await client.get(f"{base}/leads?stage=invite_pending", headers=auth(token))).json()
    assert pending["total"] == 1 and pending["items"][0]["days_waiting"] == 3

    bad = await client.get(f"{base}/leads?stage=nonsense", headers=auth(token))
    assert bad.status_code == 404


async def test_tracking_is_private_to_the_workspace(client: AsyncClient, db: Any) -> None:
    _, ws, campaign_id = await _enrolled_campaign(client, db)
    other = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": "intruder@example.com",
            "password": "correct horse 7",
            "full_name": "Intruder",
            "workspace_name": "Other",
        },
    )
    other_token = other.json()["access_token"]

    response = await client.get(
        f"/api/v1/workspaces/{ws}/campaigns/{campaign_id}/tracking", headers=auth(other_token)
    )
    assert response.status_code == 404


async def test_csv_export_lists_every_lead(client: AsyncClient, db: Any) -> None:
    token, ws, campaign_id = await _enrolled_campaign(client, db)
    response = await client.get(
        f"/api/v1/workspaces/{ws}/campaigns/{campaign_id}/tracking/export.csv", headers=auth(token)
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    lines = response.text.strip().splitlines()
    assert len(lines) == 5  # header + 4 leads
    assert "Queued" in lines[1]


# ── an empty inbox is not a failure ──────────────────────────────────────────


class _FakePage:
    def __init__(self, text: str | None) -> None:
        self.text = text

    def locator(self, _: str) -> Any:
        page = self

        class _Body:
            def inner_text(self, timeout: int = 0) -> str:
                if page.text is None:
                    raise RuntimeError("page gone")
                return page.text

        return _Body()


def test_a_new_accounts_empty_inbox_is_recognised() -> None:
    from app.linkedin.browser_driver import BrowserDriver

    assert BrowserDriver._inbox_is_empty(_FakePage("Messaging\nNo messages yet\nSend a message"))
    assert not BrowserDriver._inbox_is_empty(_FakePage("Messaging\nAna Lee  Hello there"))
    assert not BrowserDriver._inbox_is_empty(_FakePage(None))
