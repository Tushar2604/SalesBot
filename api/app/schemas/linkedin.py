"""LinkedIn account and proxy schemas.

Note what is absent from every response model: cookies, passwords, proxy
credentials, fingerprint internals. The API returns descriptions of those
things, never the things themselves.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.linkedin import LinkedInAccountStatus, ProxyStatus

# ── proxies ──────────────────────────────────────────────────────────────────


class ProxyCreateRequest(BaseModel):
    label: str = Field(default="", max_length=120)
    provider: str = Field(default="manual", max_length=60)
    scheme: str = Field(default="http", pattern="^(http|https|socks5|socks5h)$")
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    username: str | None = None
    password: str | None = None
    country: str = Field(default="", max_length=2)
    city: str = Field(default="", max_length=80)
    sticky_session_id: str = Field(default="", max_length=120)
    # Set only after the person accepted the returned location risks.
    acknowledge_risk: bool = False

    @field_validator("country")
    @classmethod
    def _upper_country(cls, value: str) -> str:
        return value.upper()


class ProxyResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    provider: str
    # Host and port only — credentials are never echoed back.
    public_url: str
    country: str
    city: str
    status: ProxyStatus
    last_exit_ip: str
    # Measured exit country; can differ from the `country` the provider claimed.
    exit_country: str = ""
    last_checked_at: datetime | None
    assigned_account_id: uuid.UUID | None
    created_at: datetime


# ── connecting an account ────────────────────────────────────────────────────


class CookieConnectRequest(BaseModel):
    """Connect by pasting the session cookie from your own browser.

    The most reliable path: no password leaves the user's hands and no fresh
    login challenge is triggered.
    """

    label: str = Field(default="", max_length=120)
    li_at: str = Field(min_length=20, description="Value of the li_at cookie on linkedin.com")
    jsessionid: str | None = Field(default=None, description="Optional JSESSIONID cookie value")
    timezone: str = Field(default="UTC", max_length=64)
    account_id: uuid.UUID | None = Field(
        default=None,
        description="Reconnect this specific existing account instead of creating a new one, "
        "so its frozen device fingerprint is kept rather than drawing a new one.",
    )
    proxy_id: uuid.UUID | None = None

    @field_validator("li_at")
    @classmethod
    def _strip_cookie(cls, value: str) -> str:
        # Users routinely paste `li_at=AQED...` or a quoted value.
        cleaned = value.strip().strip('"').strip()
        if cleaned.lower().startswith("li_at="):
            cleaned = cleaned[6:].strip().strip('"')
        return cleaned


class CredentialsConnectRequest(BaseModel):
    """Connect with email and password. May require a verification code."""

    label: str = Field(default="", max_length=120)
    email: EmailStr
    password: str = Field(min_length=1)
    timezone: str = Field(default="UTC", max_length=64)
    proxy_id: uuid.UUID | None = None


class ChallengeSubmitRequest(BaseModel):
    code: str = Field(min_length=4, max_length=10, description="Verification code from LinkedIn")


class RemoteBrowserConnectRequest(BaseModel):
    """Connect via a real, human-driven browser session (see remote_browser/)."""

    label: str = Field(default="", max_length=120)
    timezone: str = Field(default="UTC", max_length=64)
    proxy_id: uuid.UUID | None = None


class RemoteSessionResponse(BaseModel):
    ticket: str
    ws_url: str
    expires_in: int


# ── caps ─────────────────────────────────────────────────────────────────────


class WorkingHours(BaseModel):
    start: str = Field(default="09:00", pattern=r"^\d{2}:\d{2}$")
    end: str = Field(default="17:30", pattern=r"^\d{2}:\d{2}$")


class CapsUpdateRequest(BaseModel):
    """Requested limits. The server clamps these — it never raises them."""

    daily_invites: int | None = Field(default=None, ge=1, le=100)
    daily_messages: int | None = Field(default=None, ge=1, le=100)
    daily_views: int | None = Field(default=None, ge=1, le=200)
    daily_likes: int | None = Field(default=None, ge=1, le=60)
    weekly_invites: int | None = Field(default=None, ge=1, le=200)
    working_hours: WorkingHours | None = None
    weekdays_only: bool | None = None
    test_mode: bool | None = None
    auto_like_enabled: bool | None = None
    timezone: str | None = Field(default=None, max_length=64)
    label: str | None = Field(default=None, max_length=120)
    proxy_id: uuid.UUID | None = None
    # Set only after the person has seen and accepted the risks the server
    # returned in a `risk_confirmation_required` error.
    acknowledge_risk: bool = False


class EffectiveCapsResponse(BaseModel):
    daily_invites: int
    daily_messages: int
    daily_views: int
    daily_likes: int
    weekly_invites: int
    working_hours: WorkingHours
    weekdays_only: bool
    timezone: str
    # Which rule produced daily_invites, so the number is never mysterious.
    invite_limit_reason: str


# ── account ──────────────────────────────────────────────────────────────────


class PublishingStatus(BaseModel):
    """Whether this account may publish through the official LinkedIn API.

    A verdict, never a credential: the access token behind this is never
    serialised, here or anywhere else.
    """

    code: str
    available: bool
    message: str
    # "" | "configure" | "authorize"
    remedy: str
    authorized_at: datetime | None = None
    expires_at: datetime | None = None
    scopes: list[str] = Field(default_factory=list)


class LinkedInAccountResponse(BaseModel):
    id: uuid.UUID
    label: str
    login_email: str
    public_id: str
    full_name: str
    headline: str
    avatar_url: str
    profile_url: str

    status: LinkedInAccountStatus
    status_detail: str
    needs_user_action: bool
    is_connected: bool

    health_score: int
    consecutive_errors: int
    circuit_open_until: datetime | None
    circuit_reason: str

    test_mode: bool
    caps: EffectiveCapsResponse
    within_working_hours: bool
    working_hours_detail: str
    auto_like_enabled: bool

    # Descriptions, not the underlying secrets.
    device: str
    proxy_label: str
    proxy_country: str
    using_direct_connection: bool
    warnings: list[str]
    # Safety warnings in the last 30 days, toward an automatic pause at `warning_limit`.
    warning_count: int = 0
    warning_limit: int = 3
    risk_level: str = "safe"

    publishing: PublishingStatus

    session_updated_at: datetime | None
    last_action_at: datetime | None
    next_allowed_at: datetime | None
    created_at: datetime


class PublishingAuthorizeResponse(BaseModel):
    """Where to send the user to grant posting permission."""

    authorize_url: str


class ConnectResponse(BaseModel):
    """Returned immediately; the connection itself completes in a worker."""

    account: LinkedInAccountResponse
    # What the UI should do next: "poll" while CONNECTING, "code" for 2FA,
    # "resolve" when LinkedIn wants the user on linkedin.com.
    next_step: str
    message: str


class SessionCheckResponse(BaseModel):
    status: LinkedInAccountStatus
    classification: str
    detail: str
    profile: dict[str, Any] | None = None


# ── feed ─────────────────────────────────────────────────────────────────────


class FeedPostResponse(BaseModel):
    urn: str
    author_name: str
    author_headline: str
    author_avatar_url: str
    text: str
    liked: bool
    like_count: int
    comment_count: int = 0
    image_urls: list[str] = Field(default_factory=list)
    # Set once a like on this post is queued, so the UI can show "queued"
    # without polling a second endpoint per post.
    like_pending: bool = False


class FeedResponse(BaseModel):
    posts: list[FeedPostResponse]
    fetched_at: datetime | None
    # True while a refresh is queued but the cache above is still the old one.
    refreshing: bool = False


class LikePostRequest(BaseModel):
    post_urn: str = Field(min_length=1, max_length=200)


class LikeTaskResponse(BaseModel):
    task_id: uuid.UUID
    status: str
    post_urn: str


# ── auto-like topic rules ────────────────────────────────────────────────────


class AutoLikeRules(BaseModel):
    """Which posts auto-like may pick. `exclude` always wins."""

    mode: Literal["any", "topics"] = "any"
    topics: list[str] = Field(default_factory=list, max_length=20)
    exclude: list[str] = Field(default_factory=list, max_length=20)
    # Match by meaning with the AI provider; keywords when it's off or unavailable.
    use_ai: bool = True


class AutoLikeRulesResponse(AutoLikeRules):
    auto_like_enabled: bool
    ai_available: bool
    suggested_topics: list[str]
    suggested_excludes: list[str]


class AutoLikePreviewPost(BaseModel):
    urn: str
    author_name: str
    text: str
    liked: bool
    would_like: bool
    topic: str = ""
    reason: str = ""
    matched_by: str = "keywords"


class AutoLikePreview(BaseModel):
    rules: AutoLikeRules
    posts: list[AutoLikePreviewPost]
    matching: int
