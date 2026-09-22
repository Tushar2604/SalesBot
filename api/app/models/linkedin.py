"""LinkedIn accounts and the proxies they are bound to.

The invariant this schema exists to enforce: **one LinkedIn account owns exactly
one network identity and one device identity, for life.** Parallel sessions from
different IPs are the strongest ban signal LinkedIn scores, so the proxy and the
fingerprint are written once at connect time and then treated as immutable.

Nothing here stores a plaintext secret. Session cookies and proxy credentials are
Fernet ciphertext (`app.core.crypto`), decrypted only inside a worker process.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, Timestamps, UUIDPrimaryKey


class LinkedInAccountStatus(enum.StrEnum):
    """Lifecycle of a connected account.

    The challenge states are first-class rather than transient errors: LinkedIn
    interrupts logins routinely, and a product that cannot resume a 2FA flow
    cannot connect real accounts.
    """

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    PENDING_2FA = "pending_2fa"  # app/SMS one-time code
    PENDING_EMAIL_PIN = "pending_email_pin"  # emailed verification code
    CHALLENGE = "challenge"  # captcha / device check, resolve on linkedin.com
    ACTIVE = "active"
    PAUSED = "paused"  # user-paused; no actions dispatched
    AUTH_LOST = "auth_lost"  # session expired or revoked, needs reconnect
    BLOCKED = "blocked"  # LinkedIn restricted the account
    DISABLED = "disabled"  # operator-disabled

    @property
    def is_operable(self) -> bool:
        """Whether the dispatcher may emit actions for an account in this state."""
        return self is LinkedInAccountStatus.ACTIVE

    @property
    def needs_user_action(self) -> bool:
        return self in {
            LinkedInAccountStatus.PENDING_2FA,
            LinkedInAccountStatus.PENDING_EMAIL_PIN,
            LinkedInAccountStatus.CHALLENGE,
            LinkedInAccountStatus.AUTH_LOST,
            LinkedInAccountStatus.BLOCKED,
        }


class ProxyStatus(enum.StrEnum):
    UNTESTED = "untested"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DEAD = "dead"


class Proxy(UUIDPrimaryKey, Timestamps, Base):
    """An egress identity. Residential or mobile in production.

    The binding to an account lives on `linkedin_accounts.proxy_id`, which is
    UNIQUE — one proxy serves at most one account, because two accounts on one
    IP is itself a clustering signal. Keeping the foreign key on one side only
    means there is a single source of truth for that binding.
    """

    __tablename__ = "proxies"
    __table_args__ = (Index("ix_proxies_workspace_id", "workspace_id"),)

    # Null workspace_id = shared operator pool, claimable by any tenant.
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE")
    )
    label: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(60), nullable=False, default="manual")
    scheme: Mapped[str] = mapped_column(String(10), nullable=False, default="http")
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    username_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    password_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)

    # Geo must match the account's stated location, or LinkedIn sees a
    # travelling user who never travels.
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="")
    city: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    # Provider-specific token that pins the exit IP across requests.
    sticky_session_id: Mapped[str] = mapped_column(String(120), nullable=False, default="")

    status: Mapped[ProxyStatus] = mapped_column(
        Enum(ProxyStatus, name="proxy_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
        default=ProxyStatus.UNTESTED,
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_exit_ip: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Eager by default: presenting a proxy means reporting whether it is bound,
    # and a lazy load there would be IO from sync code inside an async handler.
    assigned_account: Mapped[LinkedInAccount | None] = relationship(
        back_populates="proxy", lazy="selectin"
    )

    @property
    def assigned_account_id(self) -> uuid.UUID | None:
        return self.assigned_account.id if self.assigned_account else None

    @property
    def public_url(self) -> str:
        """Credential-free representation, safe to log or return to a client."""
        return f"{self.scheme}://{self.host}:{self.port}"


class LinkedInAccount(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "linkedin_accounts"
    __table_args__ = (
        # One workspace cannot connect the same LinkedIn profile twice: that
        # would be two sessions racing for one account's single execution slot.
        UniqueConstraint("workspace_id", "profile_urn", name="uq_linkedin_accounts_ws_profile"),
        UniqueConstraint("proxy_id", name="uq_linkedin_accounts_proxy_id"),
        Index("ix_linkedin_accounts_workspace_id", "workspace_id"),
        Index("ix_linkedin_accounts_status", "status"),
        Index("ix_linkedin_accounts_dispatch", "status", "next_allowed_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )

    label: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    login_email: Mapped[str] = mapped_column(String(320), nullable=False, default="")

    # Identity as LinkedIn reports it, filled in once a session is established.
    profile_urn: Mapped[str | None] = mapped_column(String(120))
    public_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    full_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    headline: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    avatar_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    profile_country: Mapped[str] = mapped_column(String(2), nullable=False, default="")

    status: Mapped[LinkedInAccountStatus] = mapped_column(
        Enum(
            LinkedInAccountStatus,
            name="linkedin_account_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
        default=LinkedInAccountStatus.DISCONNECTED,
    )
    status_detail: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # ── the three frozen identity pieces ────────────────────────────────────
    session_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    session_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Mobile client identity: client version, device model, OS, display metrics,
    # user agent, accept-language, timezone. Written once, never rotated —
    # rotating a fingerprint is itself the anomaly.
    fingerprint: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # UNIQUE: one proxy is never shared by two accounts. Eagerly loaded because
    # every presentation of an account reports its connection.
    proxy_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("proxies.id", ondelete="SET NULL")
    )
    proxy: Mapped[Proxy | None] = relationship(back_populates="assigned_account", lazy="selectin")

    # In-flight challenge state, so a 2FA code entered in the UI can be
    # submitted on the same session that triggered the challenge.
    challenge_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    challenge_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── safety state ─────────────────────────────────────────────────────────
    health_score: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    consecutive_errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    circuit_open_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    circuit_reason: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    # Conservative by default. `caps` may only ever be *more* conservative than
    # the ceilings in settings; the dispatcher clamps it on read.
    test_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    caps: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    ramp_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # ── official publishing grant (Content Studio) ───────────────────────────
    # Entirely separate from `session_ciphertext` above, and deliberately so:
    # that is an automation session cookie, this is a member-granted OAuth 2.0
    # access token from LinkedIn's documented 3-legged flow. Posting is only
    # ever done with this token, never with the cookie.
    publishing_token_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    publishing_refresh_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    publishing_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publishing_scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # `urn:li:person:…` as returned by /v2/userinfo — the author of every post
    # made with this grant. Stored separately from `profile_urn` because the two
    # come from different systems and must be allowed to disagree.
    publishing_member_urn: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    publishing_authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    publishing_authorized_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    publishing_error: Mapped[str] = mapped_column(Text, nullable=False, default="")

    last_action_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Log-normal pacing: the dispatcher will not touch this account until now.
    next_allowed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def is_connected(self) -> bool:
        return self.session_ciphertext is not None

    @property
    def has_publishing_grant(self) -> bool:
        return self.publishing_token_ciphertext is not None

    def circuit_is_open(self, now: datetime) -> bool:
        return self.circuit_open_until is not None and self.circuit_open_until > now
