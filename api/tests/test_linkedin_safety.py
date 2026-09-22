"""The safety engine's pure logic: classification, circuit breaker, caps, ramp.

These are the tests that matter most in this codebase. A bug here does not throw
an exception — it silently sends 75 invites from a three-day-old account, or
retries into a restriction, and the customer loses their LinkedIn account.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, time, timedelta

import pytest

from app.config import settings
from app.linkedin import caps as caps_mod
from app.linkedin import fingerprint as fp_mod
from app.linkedin import health
from app.linkedin.classify import Classification, ResponseClass, classify_response
from app.models.linkedin import LinkedInAccount, LinkedInAccountStatus

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)  # a Tuesday, midday UTC


def make_account(**overrides: object) -> LinkedInAccount:
    """An in-memory account. Never added to a session — this is pure logic."""
    defaults: dict[str, object] = {
        "id": uuid.uuid4(),
        "workspace_id": uuid.uuid4(),
        "status": LinkedInAccountStatus.ACTIVE,
        "health_score": 100,
        "consecutive_errors": 0,
        "test_mode": False,
        "caps": caps_mod.default_caps() | {"daily_invites": 75},
        "timezone": "UTC",
        "ramp_started_at": NOW - timedelta(days=60),
        "created_at": NOW - timedelta(days=60),
        "session_ciphertext": b"ciphertext",
        "fingerprint": fp_mod.generate(),
        "circuit_open_until": None,
        "circuit_reason": "",
        "next_allowed_at": None,
        "status_detail": "",
        "profile_country": "",
    }
    return LinkedInAccount(**(defaults | overrides))


# ── classification ───────────────────────────────────────────────────────────


def test_999_is_blocked_not_a_rate_limit() -> None:
    result = classify_response(status_code=999, body="")
    assert result.response_class is ResponseClass.BLOCKED
    assert result.response_class.opens_circuit
    assert not result.response_class.is_retryable


def test_restriction_page_is_blocked_even_with_a_200() -> None:
    result = classify_response(
        status_code=200, body="<html>We've restricted your account temporarily</html>"
    )
    assert result.response_class is ResponseClass.BLOCKED


def test_checkpoint_redirect_is_a_challenge() -> None:
    result = classify_response(
        status_code=302,
        body="",
        redirect_location="https://www.linkedin.com/checkpoint/challenge/AgH...",
    )
    assert result.response_class is ResponseClass.CHALLENGE
    assert "checkpoint" in result.challenge_url


def test_redirect_to_login_is_auth_lost_not_a_transport_error() -> None:
    """The regression this test exists for.

    Following redirects turned a dead session into "TooManyRedirects", which
    reads as retryable. It is not: the session is gone and retrying just
    re-attempts a doomed sign-in.
    """
    result = classify_response(
        status_code=302, body="", redirect_location="https://www.linkedin.com/login"
    )
    assert result.response_class is ResponseClass.AUTH_LOST
    assert not result.response_class.is_retryable
    assert result.response_class.opens_circuit


def test_a_bare_302_on_an_api_path_is_a_dead_session() -> None:
    """LinkedIn's real behaviour: it bounces unauthenticated Voyager calls with
    a 302 carrying no Location header at all. An authenticated API call never
    redirects, so there is nothing ambiguous to report as drift."""
    result = classify_response(
        status_code=302, body="", final_url="https://www.linkedin.com/voyager/api/me"
    )
    assert result.response_class is ResponseClass.AUTH_LOST


def test_unexpected_redirect_off_the_api_is_drift_not_a_guess() -> None:
    result = classify_response(
        status_code=302,
        body="",
        final_url="https://www.linkedin.com/feed",
        redirect_location="https://www.linkedin.com/somewhere-new",
    )
    assert result.response_class is ResponseClass.UNKNOWN_SHAPE


def test_weekly_limit_notice_is_a_soft_limit() -> None:
    result = classify_response(
        status_code=200, body='{"message": "You have reached the weekly invitation limit"}'
    )
    assert result.response_class is ResponseClass.SOFT_LIMIT
    assert result.response_class.is_retryable
    assert not result.response_class.opens_circuit


def test_429_is_rate_limited() -> None:
    assert classify_response(status_code=429, body="").response_class is ResponseClass.RATE_LIMITED


def test_401_is_auth_lost() -> None:
    assert classify_response(status_code=401, body="").response_class is ResponseClass.AUTH_LOST


def test_non_json_success_where_json_expected_is_drift() -> None:
    result = classify_response(status_code=200, body="<html>hello</html>", payload=None)
    assert result.response_class is ResponseClass.UNKNOWN_SHAPE


def test_json_success_is_ok() -> None:
    result = classify_response(status_code=200, body='{"a":1}', payload={"a": 1})
    assert result.ok


# ── circuit breaker ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("response_class", "expected_status"),
    [
        (ResponseClass.BLOCKED, LinkedInAccountStatus.BLOCKED),
        (ResponseClass.AUTH_LOST, LinkedInAccountStatus.AUTH_LOST),
        (ResponseClass.CHALLENGE, LinkedInAccountStatus.CHALLENGE),
    ],
)
def test_serious_classes_open_the_circuit_and_never_reopen_on_a_timer(
    response_class: ResponseClass, expected_status: LinkedInAccountStatus
) -> None:
    account = make_account()

    outcome = health.apply_classification(
        account, Classification(response_class, detail="x"), now=NOW
    )

    assert outcome.circuit_opened
    assert outcome.notify_user
    assert account.status is expected_status
    # Far future, not a short back-off: only a human clears this. An automatic
    # reopen would be an auto-retry into a block.
    assert account.circuit_open_until is not None
    assert account.circuit_open_until > NOW + timedelta(days=300)

    allowed, reason = health.can_dispatch(account, now=NOW)
    assert not allowed
    assert reason


def test_soft_limit_backs_off_without_disconnecting() -> None:
    account = make_account()

    outcome = health.apply_classification(
        account, Classification(ResponseClass.SOFT_LIMIT, detail="weekly limit"), now=NOW
    )

    assert not outcome.circuit_opened
    assert outcome.quota_should_halve
    assert account.status is LinkedInAccountStatus.ACTIVE
    assert account.next_allowed_at == NOW + health.SOFT_LIMIT_BACKOFF
    assert not health.can_dispatch(account, now=NOW)[0]
    # ...but it is allowed again once the back-off elapses.
    assert health.can_dispatch(account, now=NOW + timedelta(hours=7))[0]


def test_retry_after_overrides_a_shorter_backoff() -> None:
    account = make_account()
    health.apply_classification(
        account,
        Classification(ResponseClass.RATE_LIMITED, retry_after_seconds=7200),
        now=NOW,
    )
    assert account.next_allowed_at == NOW + timedelta(seconds=7200)


def test_an_error_streak_opens_the_circuit_even_when_each_error_looks_benign() -> None:
    account = make_account()

    for _ in range(8):
        outcome = health.apply_classification(
            account, Classification(ResponseClass.TRANSPORT_ERROR), now=NOW
        )

    assert outcome.circuit_opened
    assert account.consecutive_errors == 8
    assert "consecutive errors" in account.circuit_reason


def test_success_resets_the_error_streak_and_recovers_health_slowly() -> None:
    account = make_account(health_score=50, consecutive_errors=5)

    health.apply_classification(account, Classification(ResponseClass.OK), now=NOW)

    assert account.consecutive_errors == 0
    # Recovery is deliberately slow: one good call does not clear recent trouble.
    assert account.health_score == 52
    assert account.last_action_at == NOW


def test_dispatch_is_refused_without_a_session() -> None:
    allowed, reason = health.can_dispatch(make_account(session_ciphertext=None), now=NOW)
    assert not allowed
    assert "session" in reason


def test_dispatch_is_refused_for_a_paused_account() -> None:
    account = make_account(status=LinkedInAccountStatus.PAUSED)
    allowed, reason = health.can_dispatch(account, now=NOW)
    assert not allowed
    assert "paused" in reason


# ── caps and ramp-up ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("age_days", "expected"),
    [(0, 12), (3, 12), (7, 25), (13, 25), (14, 40), (20, 40), (21, 75), (90, 75)],
)
def test_ramp_curve_rises_with_account_age(age_days: int, expected: int) -> None:
    account = make_account(ramp_started_at=NOW - timedelta(days=age_days))
    assert caps_mod.ramp_ceiling(account, now=NOW) == expected


def test_a_young_account_is_capped_by_the_ramp_not_by_what_the_user_asked_for() -> None:
    account = make_account(
        ramp_started_at=NOW - timedelta(days=2), caps={"daily_invites": 75}, test_mode=False
    )

    resolved = caps_mod.resolve(account, now=NOW)

    assert resolved.daily_invites == 12
    assert resolved.invite_limit_reason == "account warm-up curve"


def test_test_mode_wins_over_everything() -> None:
    account = make_account(test_mode=True, caps={"daily_invites": 75})
    resolved = caps_mod.resolve(account, now=NOW)

    assert (
        settings.safety_test_mode_daily_invites
        <= resolved.daily_invites
        <= settings.safety_test_mode_daily_invites_max
    )
    assert resolved.invite_limit_reason == "test mode"


def test_warmup_caps_messages_and_varies_invites_across_days() -> None:
    account = make_account(test_mode=True, caps={"daily_invites": 75, "daily_messages": 50})
    days = [NOW + timedelta(days=d) for d in range(30)]
    invites = {caps_mod.resolve(account, now=d).daily_invites for d in days}

    assert invites <= {3, 4, 5}
    assert len(invites) > 1
    assert caps_mod.resolve(account, now=NOW).daily_messages == settings.safety_test_mode_daily_messages
    # Same day, same answer: every dispatcher tick must agree.
    assert caps_mod.warmup_invites(account, now=NOW) == caps_mod.warmup_invites(account, now=NOW)


def test_a_tenant_cannot_raise_limits_past_the_ceiling() -> None:
    account = make_account(caps={"daily_invites": 500, "weekly_invites": 9999})

    resolved = caps_mod.resolve(account, now=NOW)

    assert resolved.daily_invites <= settings.safety_max_daily_invites
    assert resolved.weekly_invites <= settings.safety_max_weekly_invites


def test_a_lower_request_is_honoured() -> None:
    account = make_account(caps={"daily_invites": 5})
    resolved = caps_mod.resolve(account, now=NOW)

    assert resolved.daily_invites == 5
    assert resolved.invite_limit_reason == "your configured limit"


# ── working hours ────────────────────────────────────────────────────────────


def test_working_hours_are_measured_in_the_accounts_own_timezone() -> None:
    # 12:00 UTC is 17:30 in Kolkata — the edge of the default window.
    account = make_account(
        timezone="Asia/Kolkata",
        caps=caps_mod.default_caps() | {"working_hours": {"start": "09:00", "end": "17:00"}},
    )
    allowed, reason = caps_mod.within_working_hours(account, now=NOW)
    assert not allowed
    assert "Asia/Kolkata" in reason

    # The same instant is inside a US-Eastern morning.
    us_account = make_account(
        timezone="America/New_York",
        caps=caps_mod.default_caps() | {"working_hours": {"start": "07:00", "end": "17:00"}},
    )
    assert caps_mod.within_working_hours(us_account, now=NOW)[0]


def test_weekends_are_skipped_when_weekdays_only() -> None:
    saturday = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
    account = make_account()

    allowed, reason = caps_mod.within_working_hours(account, now=saturday)

    assert not allowed
    assert "working days" in reason


def test_an_unknown_timezone_falls_back_to_utc_rather_than_crashing() -> None:
    account = make_account(timezone="Mars/Olympus_Mons")
    assert str(caps_mod.zone_for(account)) == "UTC"


def test_resolved_working_hours_are_times_not_strings() -> None:
    resolved = caps_mod.resolve(make_account(), now=NOW)
    start, end = resolved.working_hours
    assert isinstance(start, time) and isinstance(end, time)
    assert start < end


# ── frozen device identity ───────────────────────────────────────────────────


def test_fingerprints_are_internally_coherent() -> None:
    fp = fp_mod.generate(locale="en_US", timezone="Asia/Kolkata")

    assert fp["timezone"] == "Asia/Kolkata"
    assert uuid.UUID(fp["device_id"])  # a real UUID, stable for the account

    agent = fp_mod.user_agent(fp)
    assert agent.startswith("com.linkedin.android/")
    assert fp["android_release"] in agent

    track = fp_mod.li_track(fp)
    # The display metrics must belong to the same device as the model name.
    assert track["model"] == fp["model"]
    assert track["deviceFormFactor"] == "PHONE"
    assert track["osName"] == "Android OS"
    assert track["clientVersion"] == fp["client_version"]


def test_two_accounts_get_distinct_device_ids() -> None:
    assert fp_mod.generate()["device_id"] != fp_mod.generate()["device_id"]


def test_describe_never_leaks_the_device_id() -> None:
    fp = fp_mod.generate()
    assert fp["device_id"] not in fp_mod.describe(fp)
