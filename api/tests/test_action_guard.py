"""The action gap guard: one clock per LinkedIn account, enforced for every write.

These tests pin the property the whole product relies on: no path — campaign
executor, inbox reply, AI assistant, publishing, or code added later — can make
one account act twice within its gap.
"""

from __future__ import annotations

import pathlib
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import redis

from app.linkedin import guard
from app.linkedin.classify import Classification, ResponseClass
from app.linkedin.driver import ActionResult, LinkedInDriver
from app.models.linkedin import LinkedInAccount

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def _account(**extra: Any) -> LinkedInAccount:
    account = LinkedInAccount(id=uuid.uuid4(), timezone="UTC", **extra)
    guard.reset(account.id)
    return account


@pytest.fixture
def fixed_gap(monkeypatch: pytest.MonkeyPatch) -> int:
    """Make the random post-action gap a known 300 s."""
    monkeypatch.setattr("app.scheduler.pacing.sample_gap_seconds", lambda *a, **k: 300)
    return 300


# ── the rule itself ─────────────────────────────────────────────────────────


def test_a_second_action_inside_the_gap_is_refused(fixed_gap: int) -> None:
    account = _account()
    now = datetime.now(UTC)
    guard.reserve(account, guard.ActionKind.INVITE, now)
    with pytest.raises(guard.TooSoon) as refused:
        guard.reserve(account, guard.ActionKind.MESSAGE, now + timedelta(seconds=30))
    # Stored as epoch seconds in Redis, so allow float rounding.
    assert abs(refused.value.retry_at - (now + timedelta(seconds=fixed_gap))) < timedelta(
        milliseconds=5
    )


def test_the_next_action_is_allowed_once_the_gap_has_passed(fixed_gap: int) -> None:
    account = _account()
    now = datetime.now(UTC)
    guard.reserve(account, guard.ActionKind.INVITE, now)
    guard.reserve(account, guard.ActionKind.INVITE, now + timedelta(seconds=fixed_gap + 1))


def test_each_action_gets_a_fresh_random_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    gaps = iter([130, 470])
    monkeypatch.setattr("app.scheduler.pacing.sample_gap_seconds", lambda *a, **k: next(gaps))
    account = _account()
    now = datetime.now(UTC)
    first = guard.reserve(account, guard.ActionKind.VIEW_PROFILE, now)
    later = now + timedelta(seconds=131)
    second = guard.reserve(account, guard.ActionKind.INVITE, later)
    assert first - now == timedelta(seconds=130)
    assert second - later == timedelta(seconds=470)


def test_no_configuration_can_go_below_the_absolute_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(guard.settings, "safety_min_action_gap_seconds", 15)
    monkeypatch.setattr("app.scheduler.pacing.sample_gap_seconds", lambda *a, **k: 15)
    account = _account()
    now = datetime.now(UTC)
    guard.reserve(account, guard.ActionKind.MESSAGE, now)
    with pytest.raises(guard.TooSoon):
        guard.reserve(account, guard.ActionKind.MESSAGE, now + timedelta(seconds=60))
    guard.reserve(
        account,
        guard.ActionKind.MESSAGE,
        now + timedelta(seconds=guard.ABSOLUTE_MIN_GAP_SECONDS + 1),
    )


def test_accounts_have_independent_clocks(fixed_gap: int) -> None:
    one, two = _account(), _account()
    now = datetime.now(UTC)
    guard.reserve(one, guard.ActionKind.INVITE, now)
    guard.reserve(two, guard.ActionKind.INVITE, now)  # not blocked by the other account


def test_a_redis_restart_does_not_reset_the_clock(fixed_gap: int) -> None:
    """The account row is checked too, so losing Redis can't allow a burst."""
    account = _account()
    now = datetime.now(UTC)
    guard.reserve(account, guard.ActionKind.INVITE, now)
    assert account.next_allowed_at == now + timedelta(seconds=fixed_gap)
    guard.reset(account.id)  # Redis forgot everything
    with pytest.raises(guard.TooSoon):
        guard.reserve(account, guard.ActionKind.INVITE, now + timedelta(seconds=30))


def test_redis_unavailable_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    class Down:
        def eval(self, *a: Any, **k: Any) -> None:
            raise redis.ConnectionError("down")

    account = _account()
    monkeypatch.setattr(guard, "_client", lambda: Down())
    with pytest.raises(guard.TooSoon):
        guard.reserve(account, guard.ActionKind.INVITE)


def test_earliest_reports_the_same_clock_without_reserving(fixed_gap: int) -> None:
    account = _account()
    now = datetime.now(UTC)
    assert guard.earliest(account, now) == now
    guard.reserve(account, guard.ActionKind.LIKE, now)
    expected = now + timedelta(seconds=fixed_gap)
    assert abs(guard.earliest(account, now) - expected) < timedelta(milliseconds=5)


# ── the wrapped driver ──────────────────────────────────────────────────────


class _FakeDriver:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def _ok(self, name: str) -> ActionResult:
        self.calls.append(name)
        return ActionResult(classification=Classification(ResponseClass.OK))

    def send_invitation(self, urn: str, note: str = "") -> ActionResult:
        return self._ok("send_invitation")

    def send_message(self, urn: str, text: str) -> ActionResult:
        return self._ok("send_message")

    def get_profile(self, public_id: str) -> tuple[Classification, None]:
        self.calls.append("get_profile")
        return Classification(ResponseClass.OK), None

    def search_people(self, *a: Any) -> None:
        self.calls.append("search_people")

    def secret_new_write(self) -> None:
        self.calls.append("secret_new_write")

    def close(self) -> None:
        pass


def test_the_wrapped_driver_blocks_a_second_write_before_it_reaches_linkedin(
    fixed_gap: int,
) -> None:
    inner = _FakeDriver()
    driver = guard.GuardedDriver(inner, _account())
    assert driver.send_invitation("urn:li:member:1").ok
    with pytest.raises(guard.TooSoon):
        driver.send_message("urn:li:member:1", "hi")
    assert inner.calls == ["send_invitation"]  # the message never went out


def test_reads_are_not_rate_limited_by_the_guard(fixed_gap: int) -> None:
    inner = _FakeDriver()
    driver = guard.GuardedDriver(inner, _account())
    driver.send_invitation("urn:li:member:1")
    driver.get_profile("someone")
    driver.get_profile("someone-else")
    assert inner.calls == ["send_invitation", "get_profile", "get_profile"]


def test_linkedin_people_search_is_refused_outright() -> None:
    inner = _FakeDriver()
    with pytest.raises(guard.ForbiddenAction):
        guard.GuardedDriver(inner, _account()).search_people("cto")
    assert inner.calls == []


def test_an_unclassified_method_is_refused_rather_than_let_through() -> None:
    inner = _FakeDriver()
    with pytest.raises(guard.ForbiddenAction):
        guard.GuardedDriver(inner, _account()).secret_new_write()
    assert inner.calls == []


def test_posts_obey_the_same_clock(fixed_gap: int) -> None:
    class Publisher:
        posts = 0

        def create_post(self, *a: Any, **k: Any) -> str:
            Publisher.posts += 1
            return "urn:li:share:1"

    account = _account()
    guard.reserve(account, guard.ActionKind.INVITE)  # an invite just went out
    with pytest.raises(guard.TooSoon):
        guard.GuardedPublisher(Publisher(), account).create_post("hello")
    assert Publisher.posts == 0


# ── no way around it ─────────────────────────────────────────────────────────


def test_every_driver_method_is_classified() -> None:
    """Adding a method to a driver without deciding read/write fails here."""
    from app.linkedin.browser_driver import BrowserDriver
    from app.linkedin.voyager import MobileVoyagerDriver

    known = set(guard.WRITE_METHODS) | guard.READ_METHODS | guard.FORBIDDEN_METHODS
    for cls in (LinkedInDriver, BrowserDriver, MobileVoyagerDriver):
        public = {n for n in dir(cls) if not n.startswith("_") and callable(getattr(cls, n))}
        assert public <= known, f"{cls.__name__}: classify {sorted(public - known)} in guard.py"


def test_drivers_and_publishers_are_only_built_by_the_guarded_factories() -> None:
    """Constructing one directly would skip the guard."""
    allowed = {
        "BrowserDriver(": {"linkedin/__init__.py"},
        "MobileVoyagerDriver(": {"linkedin/__init__.py"},
        "LinkedInPublisher(": {"linkedin/publishing.py"},
    }
    offenders = []
    for path in APP.rglob("*.py"):
        rel = path.relative_to(APP).as_posix()
        text = path.read_text(encoding="utf-8")
        for needle, homes in allowed.items():
            for match in re.finditer(re.escape(needle), text):
                line = text[: match.start()].rsplit("\n", 1)[-1]
                if line.lstrip().startswith("class ") or rel in homes:
                    continue
                offenders.append(f"{rel}: {needle}")
    assert offenders == []


def test_build_driver_always_returns_a_guarded_driver() -> None:
    from app.linkedin import build_driver

    driver = build_driver(_account(fingerprint={}, proxy=None), with_session=False)
    assert isinstance(driver, guard.GuardedDriver)


# ── every product path shares the one clock ─────────────────────────────────


def test_an_inbox_reply_then_a_campaign_action_share_the_gap(
    monkeypatch: pytest.MonkeyPatch, sdb: Any, fixed_gap: int
) -> None:
    """A reply (person or assistant) and a campaign action are spaced from
    each other, not just from their own kind."""
    from contextlib import contextmanager

    from app.models.inbox import Conversation
    from app.scheduler import dispatcher
    from app.worker.tasks import sync as sync_tasks
    from tests.test_inbox import make_account, make_workspace

    @contextmanager
    def _no_lock(*_a: Any, **_k: Any) -> Any:
        yield

    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)  # has a session, so it counts as connected
    guard.reset(account.id)
    convo = Conversation(
        workspace_id=workspace.id,
        linkedin_account_id=account.id,
        conversation_urn="thread-g",
        participant_urn="ACoAAx",
        participant_name="X",
    )
    sdb.add(convo)
    sdb.flush()
    inner = _FakeDriver()
    monkeypatch.setattr(
        sync_tasks, "build_driver", lambda acct, **k: guard.GuardedDriver(inner, acct)
    )
    monkeypatch.setattr(sync_tasks.locks, "account_slot", _no_lock)

    first = sync_tasks.deliver_text(sdb, convo, "thanks!", "human")
    assert first["ok"] is True
    second = sync_tasks.deliver_text(sdb, convo, "one more thing", "bot")
    assert second["ok"] is False and second["reason"] == "action gap"
    assert inner.calls == ["send_message"]

    # The campaign dispatcher sees the same clock and won't claim a task.
    blocked = dispatcher.evaluate_gates(sdb, account, workspace, datetime.now(UTC))
    assert blocked.startswith(("pacing", "action gap"))


def test_a_held_back_manual_reply_is_rescheduled_not_dropped(
    monkeypatch: pytest.MonkeyPatch, sdb: Any
) -> None:
    from app.worker.tasks import sync as sync_tasks
    from tests.test_inbox import _bind_session_scope

    retry_at = datetime.now(UTC) + timedelta(minutes=4)
    monkeypatch.setattr(
        sync_tasks,
        "deliver_text",
        lambda *a, **k: {"ok": False, "reason": "action gap", "retry_at": retry_at.isoformat()},
    )
    queued: list[dict[str, Any]] = []
    monkeypatch.setattr(sync_tasks.send_reply, "apply_async", lambda **kw: queued.append(kw))
    monkeypatch.setattr(sdb, "get", lambda *a, **k: object())  # any conversation
    with _bind_session_scope(monkeypatch, sync_tasks, sdb):
        result = sync_tasks.send_reply("c1", "hello")
    assert result["reason"] == "action gap"
    assert queued and queued[0]["eta"] >= retry_at
    assert queued[0]["args"] == ["c1", "hello", "human", 2]
