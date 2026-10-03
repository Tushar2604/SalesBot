"""The action gap guard: the one timing rule every LinkedIn write obeys.

Every outward action an account takes — connection request, message, profile
view, like, invitation withdrawal, post — must come at least a human-like gap
after that same account's previous one. It doesn't matter which part of the
product asked: the campaign engine, a reply typed in the inbox, the AI
assistant, feed likes or content publishing all share the one clock.

Why it is enforced here rather than by each caller
--------------------------------------------------
Each caller used to space its own actions, and one of them (the campaign
dispatcher) never checked the gap at all, so a busy campaign could act once a
minute. A rule every caller must remember is a rule some caller forgets. So
the check lives underneath them:

* `build_driver` hands out a `GuardedDriver`; its write methods call
  `reserve()` before touching LinkedIn and raise `TooSoon` when the gap has
  not passed. No caller can skip it, and one that forgets to handle it fails
  closed — the action simply doesn't happen.
* `build_publisher` does the same for posts.
* `tests/test_action_guard.py` fails if a driver is constructed anywhere
  else, or if a new driver method is added without being classed as a read or
  a write — so future code can't route around it either.

How the gap is decided
----------------------
After each write the account gets a fresh random wait from the log-normal
pacing curve (2-10 min, median ~5 by default), never a fixed interval. The
next write must wait for that, and never less than `ABSOLUTE_MIN_GAP_SECONDS`
whatever the configuration says.

The record lives in Redis, checked and updated atomically in one Lua call, so
two workers can never both pass for the same account. It is mirrored onto the
account row (`next_allowed_at`, `last_action_at`) and that is read too, so a
Redis restart does not reset anyone's clock.

This lowers the risk of detection; nothing can promise LinkedIn will never
notice automation. It is one layer next to daily caps, warm-up, working hours,
one-action-at-a-time and the circuit breaker.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast

import redis

from app.config import settings
from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.models.linkedin import LinkedInAccount

log = get_logger(__name__)

# The floor under every configuration: no setting, env var or tenant can make
# one account act twice within this many seconds.
ABSOLUTE_MIN_GAP_SECONDS = 90

# Keep the record well past any gap, but let idle accounts' keys expire.
_RECORD_TTL_SECONDS = 3 * 24 * 3600


class ActionKind(enum.StrEnum):
    INVITE = "invite"
    MESSAGE = "message"
    VIEW_PROFILE = "view_profile"
    LIKE = "like"
    WITHDRAW = "withdraw"
    POST = "post"


class TooSoon(Exception):
    """The account acted too recently. Nothing was sent; try at `retry_at`."""

    def __init__(self, account_id: uuid.UUID | str, kind: ActionKind, retry_at: datetime) -> None:
        self.account_id = str(account_id)
        self.kind = kind
        self.retry_at = retry_at
        wait = max(0, int((retry_at - datetime.now(UTC)).total_seconds()))
        super().__init__(
            f"action gap: this account acted too recently; {kind.value} can go in {wait}s"
        )


class ForbiddenAction(Exception):
    """An action this product never performs through a member's session."""


def min_gap_seconds() -> int:
    return max(ABSOLUTE_MIN_GAP_SECONDS, settings.safety_min_action_gap_seconds)


def _sample_next_gap() -> int:
    # Imported here: pacing imports caps, which imports models — keep this
    # module importable from the model layer's neighbours without a cycle.
    from app.scheduler import pacing

    return max(min_gap_seconds(), pacing.sample_gap_seconds())


def _key(account_id: uuid.UUID | str) -> str:
    return f"li:acct:{account_id}:gap"


# Atomic check-and-reserve. Returns {1, next} when the action may go (and
# records it), or {0, earliest} when it must wait.
_RESERVE = """
local last = tonumber(redis.call('HGET', KEYS[1], 'last') or '0')
local nxt = tonumber(redis.call('HGET', KEYS[1], 'next') or '0')
local now = tonumber(ARGV[1])
local min_gap = tonumber(ARGV[2])
local new_next = tonumber(ARGV[3])
local floor = tonumber(ARGV[4])
local earliest = math.max(last + min_gap, nxt, floor)
if now < earliest then
  return {0, tostring(earliest)}
end
redis.call('HSET', KEYS[1], 'last', ARGV[1], 'next', ARGV[3])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[5]))
return {1, ARGV[3]}
"""

_pool: redis.ConnectionPool | None = None


def _client() -> redis.Redis:
    global _pool
    if _pool is None:
        _pool = redis.ConnectionPool.from_url(settings.redis_url, decode_responses=True)
    return redis.Redis(connection_pool=_pool)


def _ts(moment: datetime | None) -> float:
    if moment is None:
        return 0.0
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.timestamp()


def _from_ts(value: float) -> datetime:
    return datetime.fromtimestamp(value, tz=UTC)


def _db_floor(account: LinkedInAccount) -> float:
    """What the account row says, so a Redis restart can't reset the clock."""
    return _ts(account.next_allowed_at)


@dataclass(slots=True)
class Clearance:
    allowed: bool
    # When the next write may happen (the future one we just set, when allowed).
    at: datetime


def earliest(account: LinkedInAccount, now: datetime | None = None) -> datetime:
    """When this account may next write. Read-only: for planning (the
    dispatcher, the assistant's send time), never a substitute for reserve()."""
    now = now or datetime.now(UTC)
    last = nxt = 0.0
    try:
        record = cast(dict[str, str], _client().hgetall(_key(account.id)))
        last = float(record.get("last") or 0)
        nxt = float(record.get("next") or 0)
    except redis.RedisError:
        log.warning("guard.redis_unavailable", account_id=str(account.id), exc_info=True)
    at = max(last + min_gap_seconds(), nxt, _db_floor(account), _ts(now))
    return _from_ts(at)


def reserve(account: LinkedInAccount, kind: ActionKind, now: datetime | None = None) -> datetime:
    """Claims the right to write now, or raises TooSoon.

    On success the account's next allowed time is moved to a fresh random gap
    from now, in Redis and on the account row (which the caller's session
    commits). Fails closed: if Redis is unreachable, nothing is sent.
    """
    now = now or datetime.now(UTC)
    next_at = now + timedelta(seconds=_sample_next_gap())
    try:
        allowed, value = cast(
            list[Any],
            _client().eval(
                _RESERVE,
                1,
                _key(account.id),
                repr(_ts(now)),
                str(min_gap_seconds()),
                repr(_ts(next_at)),
                repr(_db_floor(account)),
                str(_RECORD_TTL_SECONDS),
            ),
        )
    except redis.RedisError as exc:
        log.error("guard.redis_unavailable", account_id=str(account.id), error=str(exc))
        raise TooSoon(account.id, kind, now + timedelta(minutes=2)) from exc

    if not int(allowed):
        retry_at = _from_ts(float(value))
        log.info(
            "guard.too_soon",
            account_id=str(account.id),
            kind=kind.value,
            retry_at=retry_at.isoformat(),
        )
        raise TooSoon(account.id, kind, retry_at)

    account.next_allowed_at = next_at
    account.last_action_at = now
    log.info(
        "guard.reserved",
        account_id=str(account.id),
        kind=kind.value,
        next_allowed_at=next_at.isoformat(),
    )
    return next_at


def reset(account_id: uuid.UUID | str) -> None:
    """Forget an account's record (tests, and deleting an account)."""
    _client().delete(_key(account_id))


# ── the wrapped driver ───────────────────────────────────────────────────────

# Every public method of LinkedInDriver is exactly one of these. A test fails
# when a new one is added without being classified, so a new write can never
# slip past the guard unnoticed.
WRITE_METHODS: dict[str, ActionKind] = {
    "send_invitation": ActionKind.INVITE,
    "send_message": ActionKind.MESSAGE,
    "view_profile": ActionKind.VIEW_PROFILE,
    "like_post": ActionKind.LIKE,
    "withdraw_invitation": ActionKind.WITHDRAW,
}
READ_METHODS: frozenset[str] = frozenset(
    {
        "authenticate_with_cookie",
        "authenticate_with_credentials",
        "submit_challenge",
        "verify_session",
        "get_profile",
        "list_conversations",
        "get_network_distance",
        "get_connection_status",
        "warm_session",
        "get_feed",
        "close",
    }
)
# Searching LinkedIn with a member's session is what got accounts banned; the
# lead finder uses licensed data providers instead.
FORBIDDEN_METHODS: frozenset[str] = frozenset({"search_people"})


class GuardedDriver:
    """A LinkedInDriver whose writes must pass `reserve()` first.

    Reads pass straight through. Anything not explicitly known is refused, so
    an unclassified new method fails loudly instead of silently bypassing the
    gap.
    """

    def __init__(self, inner: Any, account: LinkedInAccount) -> None:
        self._inner = inner
        self._account = account

    def __getattr__(self, name: str) -> Any:
        target = getattr(self._inner, name)
        if name.startswith("_") or not callable(target):
            return target
        if name in FORBIDDEN_METHODS:
            raise ForbiddenAction(
                f"{name} is disabled: searching LinkedIn through a member's session gets "
                "accounts restricted. Use the AI lead finder (licensed data providers)."
            )
        kind = WRITE_METHODS.get(name)
        if kind is not None:

            def guarded(*args: Any, **kwargs: Any) -> Any:
                reserve(self._account, kind)
                return target(*args, **kwargs)

            return guarded
        if name in READ_METHODS:
            return target
        raise ForbiddenAction(
            f"{name} is not classified as a read or a write in app/linkedin/guard.py"
        )

    def __enter__(self) -> GuardedDriver:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class GuardedPublisher:
    """A LinkedInPublisher whose post creation must pass `reserve()` first.
    Media uploads are not visible to anyone until the post exists, so they
    pass through."""

    def __init__(self, inner: Any, account: LinkedInAccount) -> None:
        self._inner = inner
        self._account = account

    def create_post(self, *args: Any, **kwargs: Any) -> Any:
        reserve(self._account, ActionKind.POST)
        return self._inner.create_post(*args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def __enter__(self) -> GuardedPublisher:
        self._inner.__enter__()
        return self

    def __exit__(self, *exc: object) -> Any:
        return self._inner.__exit__(*exc)
