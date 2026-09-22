"""Remote-browser login (Phase 1): the pure, DB/Redis-free pieces.

The session manager itself (Playwright launch, CDP screencast, cookie
hand-off) is exercised manually against a real Chromium instance — see the
plan's verification section — since mocking Playwright's CDP event model
faithfully would test the mock more than the code. What's covered here is
everything that doesn't need a browser: fingerprint coherence and ticket
correctness, both of which are easy to get subtly wrong and easy to verify
without one.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.core.security import TokenError, decode_ws_ticket, encode_ws_ticket
from app.linkedin.remote_browser import browser_fingerprint


# ── browser_fingerprint ──────────────────────────────────────────────────────


def test_generate_is_internally_coherent() -> None:
    fp = browser_fingerprint.generate(locale="en-US", timezone="Asia/Kolkata")
    assert fp["locale"] == "en-US"
    assert fp["timezone"] == "Asia/Kolkata"
    assert fp["schema"] == 1
    vp = browser_fingerprint.viewport(fp)
    assert vp["width"] > 0
    assert vp["height"] > 0


def test_user_agent_embeds_the_chrome_version() -> None:
    fp = browser_fingerprint.generate()
    ua = browser_fingerprint.user_agent(fp)
    assert fp["chrome_version"] in ua
    assert "Chrome/" in ua


def test_describe_handles_missing_fingerprint() -> None:
    assert browser_fingerprint.describe({}) == "not assigned"


def test_describe_is_a_readable_summary() -> None:
    fp = browser_fingerprint.generate()
    text = browser_fingerprint.describe(fp)
    assert fp["chrome_version"] in text
    assert fp["platform"] in text


# ── WS tickets ────────────────────────────────────────────────────────────────


def test_ws_ticket_round_trips_its_claims() -> None:
    user_id, workspace_id, account_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    token, jti, _expires_at = encode_ws_ticket(
        user_id, workspace_id, account_id, timedelta(seconds=30)
    )
    claims = decode_ws_ticket(token)
    assert claims["sub"] == str(user_id)
    assert claims["ws"] == str(workspace_id)
    assert claims["acct"] == str(account_id)
    assert claims["jti"] == jti
    assert claims["typ"] == "remote_browser"


def test_ws_ticket_rejects_a_tampered_token() -> None:
    token, _jti, _expires_at = encode_ws_ticket(
        uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), timedelta(seconds=30)
    )
    with pytest.raises(TokenError):
        decode_ws_ticket(token[:-2] + "xy")


def test_ws_ticket_expires() -> None:
    token, _jti, _expires_at = encode_ws_ticket(
        uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), timedelta(seconds=-1)
    )
    with pytest.raises(TokenError):
        decode_ws_ticket(token)


def test_ws_ticket_is_not_accepted_as_an_access_token() -> None:
    """A separate function family from decode_token — this just confirms the
    two token universes don't cross: an access-token decoder should not be
    fooled by a `typ` it wasn't looking for landing on the same secret."""
    from app.core.security import decode_token

    token, _jti, _expires_at = encode_ws_ticket(
        uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), timedelta(seconds=30)
    )
    with pytest.raises(TokenError):
        decode_token(token, "access")
