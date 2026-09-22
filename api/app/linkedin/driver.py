"""The LinkedIn driver seam.

Every LinkedIn call in the system goes through this interface. That is the whole
point: the private API changes without notice, so breakage must be a localised
fix behind one boundary rather than a rewrite. A second implementation (a real
browser session, or a third-party account API) can be dropped in without any
caller changing.

Callers never see HTTP. They get typed results and a `Classification`, which is
what the safety engine acts on.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from app.linkedin.classify import Classification, ResponseClass


class ConnectionStatus(enum.StrEnum):
    """What a profile shows about our relationship with that person."""

    CONNECTED = "connected"
    PENDING = "pending"  # our invite is waiting for an answer
    NOT_CONNECTED = "not_connected"  # no pending invite, not a connection
    UNKNOWN = "unknown"  # the page did not show enough to say


@dataclass(slots=True)
class SessionBundle:
    """Everything needed to resume an authenticated session.

    Stored as Fernet ciphertext. Never logged, never returned by the API.
    """

    cookies: dict[str, str]
    csrf_token: str
    established_at: datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "cookies": self.cookies,
            "csrf_token": self.csrf_token,
            "established_at": self.established_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionBundle:
        return cls(
            cookies=dict(data["cookies"]),
            csrf_token=str(data["csrf_token"]),
            established_at=datetime.fromisoformat(data["established_at"]),
        )


@dataclass(slots=True)
class ChallengeContext:
    """Opaque state needed to resume an interrupted login.

    LinkedIn ties a verification code to the session that triggered it, so the
    cookies and challenge parameters must survive the round trip to the UI.
    """

    kind: str  # "2fa" | "email_pin" | "unknown"
    cookies: dict[str, str]
    csrf_token: str
    challenge_url: str
    params: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "cookies": self.cookies,
            "csrf_token": self.csrf_token,
            "challenge_url": self.challenge_url,
            "params": self.params,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChallengeContext:
        return cls(
            kind=str(data.get("kind", "unknown")),
            cookies=dict(data.get("cookies", {})),
            csrf_token=str(data.get("csrf_token", "")),
            challenge_url=str(data.get("challenge_url", "")),
            params=dict(data.get("params", {})),
        )


@dataclass(slots=True)
class AuthResult:
    """Outcome of an authentication attempt."""

    classification: Classification
    session: SessionBundle | None = None
    challenge: ChallengeContext | None = None

    @property
    def ok(self) -> bool:
        return self.session is not None and self.classification.ok

    @property
    def needs_challenge(self) -> bool:
        return self.challenge is not None


@dataclass(slots=True)
class ProfileSnapshot:
    """A LinkedIn member as we care about them."""

    urn: str = ""
    public_id: str = ""
    first_name: str = ""
    last_name: str = ""
    headline: str = ""
    location: str = ""
    country: str = ""
    company: str = ""
    title: str = ""
    avatar_url: str = ""
    # Everything else the response carried, for templating and AI context.
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


@dataclass(slots=True)
class ActionResult:
    """Outcome of a write action (invite, message, like, endorse...)."""

    classification: Classification
    # Identifier LinkedIn assigned, when it returns one (invitation urn,
    # message urn). Used to correlate later events back to this action.
    remote_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.classification.ok


@dataclass(slots=True)
class MessageEvent:
    """One message within a thread, as embedded in the conversations list.

    LinkedIn's conversations response carries a short `events` array per
    thread already; this is not a full-history read, just whatever page of
    recent events came back with the list.
    """

    event_urn: str = ""
    from_me: bool = True
    text: str = ""
    sent_at: datetime | None = None


@dataclass(slots=True)
class ConversationSnapshot:
    """One messaging thread, reduced to what reply detection needs."""

    conversation_urn: str
    participant_urn: str = ""
    participant_name: str = ""
    last_activity_at: datetime | None = None
    last_message_text: str = ""
    last_message_from_me: bool = True
    unread: bool = False
    raw: dict[str, Any] = field(default_factory=dict)
    # Recent events embedded in the same response, newest first — a small
    # amount of backlog for the inbox, not a full-thread read.
    events: list[MessageEvent] = field(default_factory=list)


@dataclass(slots=True)
class SearchPage:
    """One page of people-search results."""

    profiles: list[ProfileSnapshot]
    total: int = 0
    next_start: int | None = None
    classification: Classification = field(default_factory=lambda: Classification(ResponseClass.OK))


class LinkedInDriver(Protocol):
    """What every implementation must provide.

    Implementations are constructed per account, holding that account's frozen
    fingerprint, its proxy, and its session. They are single-use and not
    thread-safe by design: one account has one execution slot.
    """

    # ── authentication ───────────────────────────────────────────────────────
    def authenticate_with_cookie(
        self,
        li_at: str,
        jsessionid: str | None = None,
        cookies: dict[str, str] | None = None,
    ) -> AuthResult:
        """Adopt a session cookie the user supplied from their own browser."""
        ...

    def authenticate_with_credentials(self, email: str, password: str) -> AuthResult:
        """Sign in. May return a challenge instead of a session."""
        ...

    def submit_challenge(self, challenge: ChallengeContext, code: str) -> AuthResult:
        """Complete a 2FA/PIN challenge on the session that raised it."""
        ...

    def verify_session(self) -> tuple[Classification, ProfileSnapshot | None]:
        """Cheap liveness probe that also returns who we are signed in as."""
        ...

    # ── reads ────────────────────────────────────────────────────────────────
    def get_profile(self, public_id: str) -> tuple[Classification, ProfileSnapshot | None]: ...

    def view_profile(self, public_id: str) -> ActionResult:
        """A deliberate profile view — the cheap action used to warm a session."""
        ...

    def search_people(self, keywords: str, start: int = 0, count: int = 10) -> SearchPage: ...

    def list_conversations(
        self, limit: int = 20
    ) -> tuple[Classification, list[ConversationSnapshot]]: ...

    def get_network_distance(self, public_id: str) -> tuple[Classification, int | None]:
        """Degrees of separation; 1 means connected. Drives acceptance detection."""
        ...

    def get_connection_status(
        self, public_id: str
    ) -> tuple[Classification, ConnectionStatus]:
        """Connected, invite pending, or neither. Drives acceptance tracking.

        `UNKNOWN` means the page was unreadable; callers must never treat it as
        "declined".
        """
        ...

    def warm_session(self) -> Classification:
        """Read the feed the way an opening app would, before any write."""
        ...

    # ── writes ───────────────────────────────────────────────────────────────
    def send_invitation(self, profile_urn: str, note: str = "") -> ActionResult: ...

    def withdraw_invitation(self, invitation_urn: str) -> ActionResult: ...

    def send_message(self, profile_urn: str, text: str) -> ActionResult: ...

    def close(self) -> None:
        """Release the HTTP client and its proxy connection."""
        ...
