"""Publishing through LinkedIn's **official, documented** API.

This module is deliberately separate from `voyager.py`. That driver speaks a
private mobile API using a session cookie, which is the right tool for the
automation product and the wrong tool — categorically — for publishing content on
a member's behalf. Posting is only ever done here, with an access token the
member granted through LinkedIn's own 3-legged OAuth consent screen.

What that means in practice, and what the rest of the system relies on:

* No cookie, fingerprint, or proxy is involved. These requests go out directly.
* If the deployment has no LinkedIn app, or the member has not granted
  `w_member_social`, `capability_for()` says so and nothing is published. A
  missing capability is reported, never worked around and never faked.
* Every endpoint here is documented and versioned (`LinkedIn-Version` header).

References: OAuth 2.0 3-legged flow, OpenID Connect `userinfo`, Posts API,
Images/Videos/Documents upload APIs.
"""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from urllib.parse import urlencode

import httpx
import jwt

from app.config import settings
from app.core.crypto import SecretCryptoError, decrypt_str, encrypt_str
from app.core.logging import get_logger
from app.models.content import MediaKind
from app.models.linkedin import LinkedInAccount

log = get_logger(__name__)

AUTHORIZE_URL: Final[str] = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL: Final[str] = "https://www.linkedin.com/oauth/v2/accessToken"  # noqa: S105 - a URL

# The scope without which nothing in this module can work.
POST_SCOPE: Final[str] = "w_member_social"
# The scope a future analytics read would need. Absent today; its absence is why
# the UI says "analytics unavailable" instead of showing invented numbers.
ANALYTICS_SCOPE: Final[str] = "r_member_social"

# Treat a token expiring within this window as already expired, so a publish does
# not start with a credential that dies mid-upload.
EXPIRY_SKEW = timedelta(minutes=5)

MAX_COMMENTARY_CHARS: Final[int] = 3000


class CapabilityCode(enum.StrEnum):
    """Why publishing is or is not possible for one account, right now."""

    READY = "ready"
    NOT_CONFIGURED = "not_configured"  # deployment has no LinkedIn app
    NOT_AUTHORIZED = "not_authorized"  # member never granted access
    EXPIRED = "expired"  # grant lapsed
    MISSING_SCOPE = "missing_scope"  # granted, but not w_member_social
    REVOKED = "revoked"  # LinkedIn rejected the stored token


@dataclass(slots=True)
class PublishingCapability:
    """A capability answer the UI can render without further interpretation."""

    code: CapabilityCode
    message: str
    # What the user can do about it: "" | "configure" | "authorize"
    remedy: str = ""

    @property
    def available(self) -> bool:
        return self.code is CapabilityCode.READY

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "available": self.available,
            "message": self.message,
            "remedy": self.remedy,
        }


def capability_for(
    account: LinkedInAccount, *, now: datetime | None = None
) -> PublishingCapability:
    """Whether this account can publish, and if not, precisely why."""
    now = now or datetime.now(UTC)

    if not settings.linkedin_publishing_configured:
        return PublishingCapability(
            CapabilityCode.NOT_CONFIGURED,
            "Publishing to LinkedIn is not configured on this deployment. An "
            "administrator must register a LinkedIn app with the “Share on "
            "LinkedIn” product and set LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET.",
            remedy="configure",
        )

    if account.publishing_token_ciphertext is None:
        return PublishingCapability(
            CapabilityCode.NOT_AUTHORIZED,
            "This LinkedIn account has not authorized posting yet. Connect it for "
            "publishing to grant permission on LinkedIn.",
            remedy="authorize",
        )

    if POST_SCOPE not in (account.publishing_scopes or []):
        return PublishingCapability(
            CapabilityCode.MISSING_SCOPE,
            f"The LinkedIn authorization for this account is missing the "
            f"“{POST_SCOPE}” permission, which is required to create posts. "
            "Reauthorize and accept the posting permission.",
            remedy="authorize",
        )

    expires_at = account.publishing_token_expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at - EXPIRY_SKEW <= now:
            return PublishingCapability(
                CapabilityCode.EXPIRED,
                "The LinkedIn authorization for this account has expired. "
                "Reconnect it to resume publishing.",
                remedy="authorize",
            )

    if not account.publishing_member_urn:
        return PublishingCapability(
            CapabilityCode.NOT_AUTHORIZED,
            "The LinkedIn authorization is incomplete — the member identity is "
            "missing. Reauthorize this account.",
            remedy="authorize",
        )

    return PublishingCapability(CapabilityCode.READY, "Ready to publish.")


def analytics_capability(account: LinkedInAccount) -> PublishingCapability:
    """Whether post analytics can be read. Today: essentially never.

    Kept as a real check rather than a hardcoded "no" so that the day a
    deployment's app is granted the scope, the UI starts working without a code
    change — and until then it reports unavailability instead of inventing data.
    """
    base = capability_for(account)
    if not base.available:
        return base
    if ANALYTICS_SCOPE not in (account.publishing_scopes or []):
        return PublishingCapability(
            CapabilityCode.MISSING_SCOPE,
            "Post analytics require the r_member_social permission, which this "
            "LinkedIn app has not been granted.",
            remedy="configure",
        )
    return PublishingCapability(CapabilityCode.READY, "Analytics available.")


# ── OAuth ────────────────────────────────────────────────────────────────────


STATE_TTL = timedelta(minutes=15)


@dataclass(slots=True)
class OAuthState:
    workspace_id: uuid.UUID
    account_id: uuid.UUID
    user_id: uuid.UUID


def encode_state(workspace_id: uuid.UUID, account_id: uuid.UUID, user_id: uuid.UUID) -> str:
    """Signed, short-lived state parameter.

    This is the CSRF defence for the OAuth round trip: the callback is a public
    endpoint, and without a signed state anyone could hand us a code and have it
    bound to someone else's account. Signed with the app's own JWT secret, so a
    forged state cannot be constructed off-box.
    """
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "typ": "li_publish_state",
            "ws": str(workspace_id),
            "acc": str(account_id),
            "sub": str(user_id),
            "iat": int(now.timestamp()),
            "exp": int((now + STATE_TTL).timestamp()),
        },
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_state(state: str) -> OAuthState:
    try:
        payload = jwt.decode(
            state,
            settings.jwt_secret.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["exp", "sub", "typ"]},
        )
    except jwt.InvalidTokenError as exc:
        raise PublishingError(
            "that authorization link has expired; start the connection again",
            code="invalid_state",
        ) from exc

    if payload.get("typ") != "li_publish_state":
        raise PublishingError("invalid authorization state", code="invalid_state")
    try:
        return OAuthState(
            workspace_id=uuid.UUID(str(payload["ws"])),
            account_id=uuid.UUID(str(payload["acc"])),
            user_id=uuid.UUID(str(payload["sub"])),
        )
    except (KeyError, ValueError) as exc:
        raise PublishingError("invalid authorization state", code="invalid_state") from exc


def authorize_url(state: str) -> str:
    """LinkedIn's consent screen for this deployment's app."""
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.linkedin_client_id,
            "redirect_uri": settings.linkedin_redirect_uri,
            "state": state,
            "scope": " ".join(settings.linkedin_scope_list),
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


@dataclass(slots=True)
class GrantedToken:
    access_token: str
    expires_at: datetime | None
    scopes: list[str]
    refresh_token: str = ""
    member_urn: str = ""
    member_name: str = ""
    member_picture: str = ""


class PublishingError(Exception):
    """A publish attempt failed. Carries what the UI and a retry need."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "publish_failed",
        request_id: str = "",
        retryable: bool = False,
        auth_lost: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.request_id = request_id
        self.retryable = retryable
        self.auth_lost = auth_lost


def _request_id(response: httpx.Response) -> str:
    return (
        response.headers.get("x-li-uuid")
        or response.headers.get("x-restli-id")
        or response.headers.get("x-li-fabric")
        or ""
    )[:120]


def exchange_code(code: str, *, timeout: float = 20.0) -> GrantedToken:
    """Swaps an authorization code for a member access token."""
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": settings.linkedin_client_id,
                "client_secret": settings.linkedin_client_secret.get_secret_value(),
                "redirect_uri": settings.linkedin_redirect_uri,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.status_code >= 400:
            raise PublishingError(
                "LinkedIn rejected the authorization. Try connecting again.",
                code="oauth_exchange_failed",
                request_id=_request_id(response),
            )
        payload = response.json()

        access_token = str(payload.get("access_token") or "")
        if not access_token:
            raise PublishingError(
                "LinkedIn returned no access token.", code="oauth_exchange_failed"
            )

        expires_in = payload.get("expires_in")
        expires_at = (
            datetime.now(UTC) + timedelta(seconds=int(expires_in))
            if isinstance(expires_in, (int, float))
            else None
        )
        # LinkedIn returns space-delimited scopes on some apps, comma on others.
        raw_scope = str(payload.get("scope") or "")
        scopes = [s for s in raw_scope.replace(",", " ").split() if s]

        granted = GrantedToken(
            access_token=access_token,
            expires_at=expires_at,
            scopes=scopes or list(settings.linkedin_scope_list),
            refresh_token=str(payload.get("refresh_token") or ""),
        )

        # OIDC userinfo gives the person URN every post must be authored by.
        info = client.get(
            f"{settings.linkedin_api_base_url}/v2/userinfo",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if info.status_code < 400:
            data = info.json()
            subject = str(data.get("sub") or "")
            if subject:
                granted.member_urn = f"urn:li:person:{subject}"
            granted.member_name = str(data.get("name") or "")
            granted.member_picture = str(data.get("picture") or "")

    return granted


def store_grant(
    account: LinkedInAccount, granted: GrantedToken, *, actor_user_id: uuid.UUID | None
) -> None:
    """Persists a grant as ciphertext. The plaintext never leaves this call."""
    account.publishing_token_ciphertext = encrypt_str(granted.access_token)
    account.publishing_refresh_ciphertext = (
        encrypt_str(granted.refresh_token) if granted.refresh_token else None
    )
    account.publishing_token_expires_at = granted.expires_at
    account.publishing_scopes = granted.scopes
    if granted.member_urn:
        account.publishing_member_urn = granted.member_urn
    account.publishing_authorized_at = datetime.now(UTC)
    account.publishing_authorized_by_id = actor_user_id
    account.publishing_error = ""
    # Fill identity gaps only — never overwrite what the user already sees.
    if granted.member_name and not account.full_name:
        account.full_name = granted.member_name
    if granted.member_picture and not account.avatar_url:
        account.avatar_url = granted.member_picture


def clear_grant(account: LinkedInAccount, *, reason: str = "") -> None:
    account.publishing_token_ciphertext = None
    account.publishing_refresh_ciphertext = None
    account.publishing_token_expires_at = None
    account.publishing_scopes = []
    account.publishing_error = reason[:500]


def load_token(account: LinkedInAccount) -> str | None:
    if not account.publishing_token_ciphertext:
        return None
    try:
        return decrypt_str(account.publishing_token_ciphertext)
    except SecretCryptoError:
        log.error(
            "linkedin.publishing.token_undecryptable",
            account_id=str(account.id),
            hint="ENCRYPTION_KEY may have changed; the account must reauthorize",
        )
        return None


# ── the publishing client ────────────────────────────────────────────────────


@dataclass(slots=True)
class UploadedMedia:
    """One asset registered with LinkedIn and ready to attach to a post."""

    urn: str
    kind: MediaKind
    alt_text: str = ""
    title: str = ""


@dataclass(slots=True)
class PublishedPost:
    urn: str
    url: str
    raw: dict[str, Any] = field(default_factory=dict)


class LinkedInPublisher:
    """One instance per publish attempt. Not thread-safe by design."""

    def __init__(self, *, access_token: str, member_urn: str, timeout: float = 60.0) -> None:
        self._token = access_token
        self._member_urn = member_urn
        self._timeout = timeout
        self._client: httpx.Client | None = None

    def __enter__(self) -> LinkedInPublisher:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self._timeout,
                base_url=settings.linkedin_api_base_url,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "LinkedIn-Version": settings.linkedin_api_version,
                    "X-Restli-Protocol-Version": "2.0.0",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    def _raise_for(self, response: httpx.Response, what: str) -> None:
        """Turns an upstream failure into a typed, user-readable error."""
        if response.status_code < 400:
            return

        request_id = _request_id(response)
        detail = ""
        try:
            body = response.json()
            detail = str(body.get("message") or body.get("error_description") or "")
        except ValueError:
            detail = (response.text or "")[:200]

        if response.status_code in (401, 403):
            raise PublishingError(
                "LinkedIn rejected the authorization for this account. "
                "Reconnect it to grant posting permission again."
                + (f" ({detail})" if detail else ""),
                code=f"http_{response.status_code}",
                request_id=request_id,
                auth_lost=True,
            )
        if response.status_code == 422:
            raise PublishingError(
                detail or f"LinkedIn rejected the {what}.",
                code="unprocessable",
                request_id=request_id,
            )
        if response.status_code == 429:
            raise PublishingError(
                "LinkedIn is rate-limiting this account. The post will be retried.",
                code="rate_limited",
                request_id=request_id,
                retryable=True,
            )
        if response.status_code >= 500:
            raise PublishingError(
                f"LinkedIn had a server error while handling the {what}.",
                code=f"http_{response.status_code}",
                request_id=request_id,
                retryable=True,
            )
        raise PublishingError(
            detail or f"LinkedIn refused the {what}.",
            code=f"http_{response.status_code}",
            request_id=request_id,
        )

    # ── asset upload ─────────────────────────────────────────────────────────

    def upload_image(self, data: bytes, *, alt_text: str = "") -> UploadedMedia:
        client = self._http()
        init = client.post(
            "/rest/images?action=initializeUpload",
            json={"initializeUploadRequest": {"owner": self._member_urn}},
        )
        self._raise_for(init, "image upload")
        value = init.json().get("value", {})
        upload_url, urn = str(value.get("uploadUrl", "")), str(value.get("image", ""))
        if not upload_url or not urn:
            raise PublishingError(
                "LinkedIn did not return an image upload target.", code="upload_init_failed"
            )
        self._put_bytes(upload_url, data)
        return UploadedMedia(urn=urn, kind=MediaKind.IMAGE, alt_text=alt_text)

    def upload_document(self, data: bytes, *, title: str = "") -> UploadedMedia:
        client = self._http()
        init = client.post(
            "/rest/documents?action=initializeUpload",
            json={"initializeUploadRequest": {"owner": self._member_urn}},
        )
        self._raise_for(init, "document upload")
        value = init.json().get("value", {})
        upload_url, urn = str(value.get("uploadUrl", "")), str(value.get("document", ""))
        if not upload_url or not urn:
            raise PublishingError(
                "LinkedIn did not return a document upload target.", code="upload_init_failed"
            )
        self._put_bytes(upload_url, data)
        return UploadedMedia(urn=urn, kind=MediaKind.DOCUMENT, title=title)

    def upload_video(self, data: bytes, *, title: str = "") -> UploadedMedia:
        """Multipart video upload: initialize, PUT each part, finalize.

        The part boundaries come from LinkedIn, not from us — it decides how the
        file is split, and every returned ETag must be echoed back in order or
        the finalize call rejects the upload.
        """
        client = self._http()
        init = client.post(
            "/rest/videos?action=initializeUpload",
            json={
                "initializeUploadRequest": {
                    "owner": self._member_urn,
                    "fileSizeBytes": len(data),
                    "uploadCaptions": False,
                    "uploadThumbnail": False,
                }
            },
        )
        self._raise_for(init, "video upload")
        value = init.json().get("value", {})
        urn = str(value.get("video", ""))
        upload_token = str(value.get("uploadToken", ""))
        instructions = value.get("uploadInstructions") or []
        if not urn or not instructions:
            raise PublishingError(
                "LinkedIn did not return a video upload target.", code="upload_init_failed"
            )

        etags: list[str] = []
        for instruction in instructions:
            first = int(instruction.get("firstByte", 0))
            last = int(instruction.get("lastByte", len(data) - 1))
            etag = self._put_bytes(str(instruction["uploadUrl"]), data[first : last + 1])
            if not etag:
                raise PublishingError(
                    "A video part upload did not return an ETag, so the upload "
                    "cannot be finalized.",
                    code="upload_part_failed",
                    retryable=True,
                )
            etags.append(etag)

        finalize = client.post(
            "/rest/videos?action=finalizeUpload",
            json={
                "finalizeUploadRequest": {
                    "video": urn,
                    "uploadToken": upload_token,
                    "uploadedPartIds": etags,
                }
            },
        )
        self._raise_for(finalize, "video finalize")
        return UploadedMedia(urn=urn, kind=MediaKind.VIDEO, title=title)

    def _put_bytes(self, url: str, data: bytes) -> str:
        """Uploads raw bytes to a LinkedIn-issued URL; returns the ETag if any.

        A plain client: the upload URL is pre-signed and must not carry our
        JSON content-type or the REST version headers.
        """
        with httpx.Client(timeout=self._timeout) as raw:
            response = raw.put(
                url, content=data, headers={"Content-Type": "application/octet-stream"}
            )
        if response.status_code >= 400:
            raise PublishingError(
                "Uploading the media to LinkedIn failed.",
                code=f"upload_http_{response.status_code}",
                request_id=_request_id(response),
                retryable=response.status_code >= 500 or response.status_code == 429,
            )
        return response.headers.get("etag", "").strip('"')

    # ── the post itself ──────────────────────────────────────────────────────

    def create_post(
        self,
        commentary: str,
        *,
        visibility: str = "PUBLIC",
        media: list[UploadedMedia] | None = None,
        idempotency_key: str = "",
    ) -> PublishedPost:
        """Creates one post. The returned URN is the durable LinkedIn id."""
        media = media or []
        body: dict[str, Any] = {
            "author": self._member_urn,
            "commentary": commentary,
            "visibility": visibility,
            "distribution": {
                "feedDistribution": "MAIN_FEED",
                "targetEntities": [],
                "thirdPartyDistributionChannels": [],
            },
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }

        content = _content_block(media)
        if content:
            body["content"] = content

        headers: dict[str, str] = {}
        if idempotency_key:
            # Belt-and-braces on top of our own publish_key: if LinkedIn honours
            # it, a retried request collapses onto the same post upstream too.
            headers["X-RestLi-Method"] = "create"
            headers["x-li-idempotency-key"] = idempotency_key[:64]

        response = self._http().post("/rest/posts", json=body, headers=headers)
        self._raise_for(response, "post")

        urn = response.headers.get("x-restli-id", "")
        if not urn:
            try:
                urn = str(response.json().get("id", ""))
            except ValueError:
                urn = ""
        if not urn:
            raise PublishingError(
                "LinkedIn accepted the post but returned no identifier, so it "
                "cannot be linked or tracked.",
                code="missing_post_id",
            )

        return PublishedPost(urn=urn, url=post_url(urn))


def _content_block(media: list[UploadedMedia]) -> dict[str, Any]:
    """Shapes the attachment section the Posts API expects."""
    if not media:
        return {}

    images = [m for m in media if m.kind is MediaKind.IMAGE]
    if len(media) > 1 and len(images) == len(media):
        return {
            "multiImage": {
                "images": [
                    {"id": m.urn, **({"altText": m.alt_text} if m.alt_text else {})}
                    for m in images
                ]
            }
        }

    first = media[0]
    entry: dict[str, Any] = {"id": first.urn}
    if first.alt_text:
        entry["altText"] = first.alt_text
    if first.kind is MediaKind.DOCUMENT and first.title:
        entry["title"] = first.title
    return {"media": entry}


def post_url(urn: str) -> str:
    """Public permalink for a post URN."""
    return f"https://www.linkedin.com/feed/update/{urn}/" if urn else ""


def build_publisher(account: LinkedInAccount) -> LinkedInPublisher:
    """Constructs a publisher for an account, or explains why it cannot."""
    capability = capability_for(account)
    if not capability.available:
        raise PublishingError(
            capability.message,
            code=capability.code.value,
            auth_lost=capability.remedy == "authorize",
        )

    token = load_token(account)
    if token is None:
        raise PublishingError(
            "The stored LinkedIn authorization could not be read. Reconnect this "
            "account for publishing.",
            code=CapabilityCode.REVOKED.value,
            auth_lost=True,
        )
    return LinkedInPublisher(access_token=token, member_urn=account.publishing_member_urn)
