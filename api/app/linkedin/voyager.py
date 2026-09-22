"""Mobile/Voyager driver — the only code in the system that speaks to LinkedIn.

No browser, no extension. Requests carry the account's frozen mobile client
identity and go out through that account's assigned proxy, which is what keeps
the two largest detection surfaces (extension scanning and browser
fingerprinting) off the table entirely.

**Endpoint volatility.** The paths in `_EP` are a private API. They move without
notice. That is expected and handled: every response passes through
`classify_response`, an unparseable success becomes `UNKNOWN_SHAPE`, and a rise
in that class across accounts is the drift alarm. When an endpoint moves, the fix
belongs here and nowhere else.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Final

import httpx

from app.core.logging import get_logger
from app.linkedin import fingerprint as fp_mod
from app.linkedin.classify import Classification, ResponseClass, classify_response
from app.linkedin.driver import (
    ActionResult,
    AuthResult,
    ChallengeContext,
    ConnectionStatus,
    ConversationSnapshot,
    MessageEvent,
    ProfileSnapshot,
    SearchPage,
    SessionBundle,
)

log = get_logger(__name__)

BASE: Final[str] = "https://www.linkedin.com"
API: Final[str] = f"{BASE}/voyager/api"


class _EP:
    """Endpoint catalogue. One place to fix when LinkedIn moves something."""

    AUTHENTICATE = f"{BASE}/uas/authenticate"
    CHALLENGE_SUBMIT = f"{BASE}/checkpoint/challenge/verify"
    ME = f"{API}/me"
    PROFILE_VIEW = f"{API}/identity/profiles/{{public_id}}/profileView"
    # Current relationship endpoint; `normInvitations` is the legacy fallback.
    INVITE_DASH = f"{API}/voyagerRelationshipsDashMemberRelationships"
    INVITE_LEGACY = f"{API}/growth/normInvitations"
    INVITE_WITHDRAW = f"{API}/growth/normInvitations/{{invitation_id}}"
    CONVERSATIONS = f"{API}/messaging/conversations"
    SEARCH_BLENDED = f"{API}/search/blended"
    FEED = f"{API}/feed/updatesV2"
    # Dedicated, cheap endpoint for "are we connected yet". Unlike fetching the
    # whole profile it does not register a profile view, so acceptance polling
    # does not spend the account's view budget or notify the prospect again.
    NETWORK_INFO = f"{API}/identity/profiles/{{public_id}}/networkinfo"


# Cookies LinkedIn considers part of an authenticated session.
_SESSION_COOKIE_NAMES: Final[tuple[str, ...]] = (
    "li_at",
    "JSESSIONID",
    "liap",
    "li_a",
    "lidc",
    "bcookie",
    "bscookie",
)

_PROFILE_ID_RE = re.compile(r"urn:li:(?:fs_miniProfile|fsd_profile|member):([^,)\s\"]+)")


def extract_profile_id(urn_or_id: str) -> str:
    """Accepts a full URN or a bare id and returns the bare id.

    Callers pass whatever LinkedIn gave them; normalising here keeps URN
    handling out of every call site.
    """
    match = _PROFILE_ID_RE.search(urn_or_id)
    return match.group(1) if match else urn_or_id


class MobileVoyagerDriver:
    """One instance per account, per unit of work. Not thread-safe by design."""

    def __init__(
        self,
        *,
        fingerprint: dict[str, Any],
        proxy_url: str | None = None,
        session: SessionBundle | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._fp = fingerprint
        self._proxy_url = proxy_url
        self._session = session
        self._timeout = timeout
        self._client: httpx.Client | None = None

    # ── plumbing ─────────────────────────────────────────────────────────────

    def _ensure_client(self) -> httpx.Client:
        if self._client is None:
            cookies = dict(self._session.cookies) if self._session else {}
            self._client = httpx.Client(
                timeout=self._timeout,
                # Redirects are never legitimate on an authenticated Voyager call;
                # following them turns a dead session into a redirect loop and
                # hides the diagnosis. The classifier reads the Location header.
                follow_redirects=False,
                proxy=self._proxy_url,
                cookies=cookies,
                headers=self._base_headers(),
                # HTTP/2 matches what a modern mobile client negotiates.
                http2=True,
            )
        return self._client

    def _base_headers(self) -> dict[str, str]:
        locale = str(self._fp.get("locale", "en_US"))
        return {
            "User-Agent": fp_mod.user_agent(self._fp),
            "X-Li-User-Agent": fp_mod.user_agent(self._fp),
            "x-li-track": json.dumps(fp_mod.li_track(self._fp), separators=(",", ":")),
            "x-li-lang": locale,
            "x-li-deviceid": str(self._fp.get("device_id", "")),
            "x-restli-protocol-version": fp_mod.RESTLI_PROTOCOL_VERSION,
            "Accept-Language": f"{locale.replace('_', '-')},{locale.split('_')[0]};q=0.9",
            "Accept": "application/json",
        }

    def _auth_headers(self) -> dict[str, str]:
        if self._session is None:
            return {}
        return {"csrf-token": self._session.csrf_token}

    def _request(
        self,
        method: str,
        url: str,
        *,
        authed: bool = True,
        expect_json: bool = True,
        **kwargs: Any,
    ) -> tuple[Classification, dict[str, Any] | None, httpx.Response | None]:
        """Single choke point for every LinkedIn call.

        Returns (classification, parsed_payload, response). Transport failures
        are classified rather than raised: a dead proxy is an operational event
        the safety engine must reason about, not an exception to leak upward.
        """
        client = self._ensure_client()
        headers = dict(kwargs.pop("headers", {}))
        if authed:
            headers.update(self._auth_headers())

        try:
            response = client.request(method, url, headers=headers, **kwargs)
        except httpx.ProxyError as exc:
            return (
                Classification(ResponseClass.TRANSPORT_ERROR, detail=f"proxy failure: {exc}"),
                None,
                None,
            )
        except httpx.HTTPError as exc:
            return (
                Classification(
                    ResponseClass.TRANSPORT_ERROR, detail=f"{type(exc).__name__}: {exc}"
                ),
                None,
                None,
            )

        payload: dict[str, Any] | None = None
        if expect_json:
            try:
                parsed = response.json()
                payload = parsed if isinstance(parsed, dict) else {"_list": parsed}
            except (json.JSONDecodeError, ValueError):
                payload = None

        classification = classify_response(
            status_code=response.status_code,
            # Cap the body: restriction pages are huge and we only match markers.
            body=response.text[:20000],
            final_url=str(response.url),
            payload=payload,
            redirect_location=response.headers.get("location", ""),
        )

        if classification.response_class is not ResponseClass.OK:
            log.warning(
                "linkedin.response",
                method=method,
                url=url.split("?")[0],
                status=response.status_code,
                classification=classification.response_class.value,
                detail=classification.detail,
            )

        return classification, payload, response

    def _collect_session(self, client: httpx.Client) -> SessionBundle | None:
        """Builds a session bundle from the client's cookie jar, if signed in."""
        jar = {
            name: value for name, value in client.cookies.items() if name in _SESSION_COOKIE_NAMES
        }
        if "li_at" not in jar:
            return None
        return SessionBundle(
            cookies=jar,
            csrf_token=jar.get("JSESSIONID", "").strip('"'),
            established_at=datetime.now(UTC),
        )

    # ── authentication ───────────────────────────────────────────────────────

    def authenticate_with_cookie(
        self,
        li_at: str,
        jsessionid: str | None = None,
        cookies: dict[str, str] | None = None,
    ) -> AuthResult:
        """Adopt a session the user copied from their own browser.

        This path avoids handing us a password and avoids triggering a fresh
        login challenge, which makes it the most reliable way to connect. The
        trade-off is that the session was born on the user's IP, so the first
        requests through a different proxy are a geo change LinkedIn can see —
        which is why account geo and proxy geo must match.
        """
        # LinkedIn accepts any well-formed JSESSIONID as the CSRF value; when
        # the user did not supply one, mint it in LinkedIn's own "ajax:N" shape.
        _ = cookies  # the httpx driver only ever needs li_at + JSESSIONID
        session_id = (jsessionid or f"ajax:{uuid.uuid4().int % 10**19}").strip('"')
        self._session = SessionBundle(
            cookies={"li_at": li_at.strip(), "JSESSIONID": f'"{session_id}"'},
            csrf_token=session_id,
            established_at=datetime.now(UTC),
        )
        self.close()  # rebuild the client with the new cookie jar

        classification, profile = self.verify_session()
        if not classification.ok or profile is None:
            self._session = None
            return AuthResult(classification=classification)
        return AuthResult(classification=classification, session=self._session)

    def authenticate_with_credentials(self, email: str, password: str) -> AuthResult:
        """Full sign-in. Returns a challenge instead of a session when LinkedIn asks.

        Two steps, as the mobile client does it: fetch the auth page to obtain
        the CSRF cookie, then post credentials against it.
        """
        self._session = None
        self.close()
        client = self._ensure_client()

        # Step 1 — seed cookies (JSESSIONID carries the CSRF token).
        seed_class, _, seed_response = self._request(
            "GET", _EP.AUTHENTICATE, authed=False, expect_json=False
        )
        if seed_class.response_class in {
            ResponseClass.BLOCKED,
            ResponseClass.TRANSPORT_ERROR,
        }:
            return AuthResult(classification=seed_class)

        # httpx types cookie lookups as optional even with a default.
        csrf = (client.cookies.get("JSESSIONID") or "").strip('"')
        if not csrf:
            # This step has no credentials in it yet, so a miss here is never
            # about the account — it means the seed page's shape changed
            # (LinkedIn moved the endpoint, or this proxy/region is served a
            # different page). Log enough to diagnose without keeping the body.
            log.warning(
                "linkedin.auth.seed_missing_jsessionid",
                status=seed_response.status_code if seed_response else None,
                final_url=str(seed_response.url) if seed_response else "",
                cookie_names=sorted(client.cookies.keys()),
                content_length=seed_response.headers.get("content-length", "")
                if seed_response
                else "",
            )
            return AuthResult(
                classification=Classification(
                    ResponseClass.UNKNOWN_SHAPE,
                    detail="LinkedIn did not issue a JSESSIONID cookie",
                )
            )

        # Step 2 — post credentials.
        classification, payload, response = self._request(
            "POST",
            _EP.AUTHENTICATE,
            authed=False,
            data={
                "session_key": email,
                "session_password": password,
                "JSESSIONID": csrf,
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "csrf-token": csrf,
            },
        )

        if classification.response_class is ResponseClass.CHALLENGE:
            return AuthResult(
                classification=classification,
                challenge=ChallengeContext(
                    kind="unknown",
                    cookies=dict(client.cookies.items()),
                    csrf_token=csrf,
                    challenge_url=classification.challenge_url
                    or (str(response.url) if response else ""),
                ),
            )

        if classification.response_class is not ResponseClass.OK:
            return AuthResult(classification=classification)

        # LinkedIn signals the outcome in the body, not the status code.
        login_result = str((payload or {}).get("login_result", "")).upper()

        if login_result == "PASS":
            session = self._collect_session(client)
            if session is None:
                return AuthResult(
                    classification=Classification(
                        ResponseClass.UNKNOWN_SHAPE,
                        detail="login reported PASS but no li_at cookie was set",
                    )
                )
            self._session = session
            return AuthResult(classification=Classification(ResponseClass.OK), session=session)

        if "CHALLENGE" in login_result:
            challenge_url = str((payload or {}).get("challenge_url", ""))
            kind = "2fa" if "2fa" in challenge_url.lower() else "unknown"
            return AuthResult(
                classification=Classification(
                    ResponseClass.CHALLENGE,
                    detail=f"login_result={login_result}",
                    challenge_url=challenge_url,
                    challenge_kind=kind,
                ),
                challenge=ChallengeContext(
                    kind=kind,
                    cookies=dict(client.cookies.items()),
                    csrf_token=csrf,
                    challenge_url=challenge_url,
                ),
            )

        if "FAIL" in login_result or "BAD" in login_result:
            return AuthResult(
                classification=Classification(
                    ResponseClass.AUTH_LOST,
                    detail="LinkedIn rejected the email or password",
                )
            )

        return AuthResult(
            classification=Classification(
                ResponseClass.UNKNOWN_SHAPE,
                detail=f"unrecognised login_result {login_result!r}",
            )
        )

    def submit_challenge(self, challenge: ChallengeContext, code: str) -> AuthResult:
        """Submit a verification code on the session that raised the challenge."""
        self._session = None
        self.close()
        client = self._ensure_client()
        for name, value in challenge.cookies.items():
            client.cookies.set(name, value, domain=".linkedin.com")

        classification, payload, _ = self._request(
            "POST",
            challenge.challenge_url or _EP.CHALLENGE_SUBMIT,
            authed=False,
            expect_json=False,
            data={**challenge.params, "pin": code, "challengeType": challenge.kind},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "csrf-token": challenge.csrf_token,
            },
        )

        session = self._collect_session(client)
        if session is not None:
            self._session = session
            return AuthResult(classification=Classification(ResponseClass.OK), session=session)

        if classification.response_class is ResponseClass.OK:
            # No error, no session: almost always a wrong or expired code.
            return AuthResult(
                classification=Classification(
                    ResponseClass.CHALLENGE,
                    detail="the code was not accepted; request a new one and retry",
                    challenge_kind=challenge.kind,
                ),
                challenge=challenge,
            )

        _ = payload
        return AuthResult(classification=classification)

    def verify_session(self) -> tuple[Classification, ProfileSnapshot | None]:
        """Cheap liveness probe. Also tells us which profile we are acting as."""
        classification, payload, _ = self._request("GET", _EP.ME)
        if not classification.ok or payload is None:
            return classification, None

        mini = payload.get("miniProfile") or {}
        if not mini:
            return (
                Classification(
                    ResponseClass.UNKNOWN_SHAPE, detail="/me response had no miniProfile"
                ),
                None,
            )

        return classification, ProfileSnapshot(
            urn=str(mini.get("entityUrn", "")),
            public_id=str(mini.get("publicIdentifier", "")),
            first_name=str(mini.get("firstName", "")),
            last_name=str(mini.get("lastName", "")),
            headline=str(mini.get("occupation", "")),
            raw=payload,
        )

    # ── reads ────────────────────────────────────────────────────────────────

    def get_profile(self, public_id: str) -> tuple[Classification, ProfileSnapshot | None]:
        classification, payload, _ = self._request(
            "GET", _EP.PROFILE_VIEW.format(public_id=public_id)
        )
        if not classification.ok or payload is None:
            return classification, None

        profile = payload.get("profile") or {}
        positions = (payload.get("positionView") or {}).get("elements") or []
        current = positions[0] if positions else {}

        return classification, ProfileSnapshot(
            urn=str(profile.get("entityUrn", "")),
            public_id=str(profile.get("publicIdentifier", public_id)),
            first_name=str(profile.get("firstName", "")),
            last_name=str(profile.get("lastName", "")),
            headline=str(profile.get("headline", "")),
            location=str(profile.get("geoLocationName") or profile.get("locationName") or ""),
            country=str(profile.get("geoCountryName", "")),
            company=str(current.get("companyName", "")),
            title=str(current.get("title", "")),
            raw=payload,
        )

    def view_profile(self, public_id: str) -> ActionResult:
        """A profile view. Cheap, visible to the prospect, and useful for warming."""
        classification, payload, _ = self._request(
            "GET", _EP.PROFILE_VIEW.format(public_id=public_id)
        )
        return ActionResult(classification=classification, payload=payload or {})

    def get_connection_status(
        self, public_id: str
    ) -> tuple[Classification, ConnectionStatus]:
        """Distance alone cannot tell a pending invite from a declined one."""
        classification, distance = self.get_network_distance(public_id)
        if not classification.ok or distance is None:
            return classification, ConnectionStatus.UNKNOWN
        return classification, (
            ConnectionStatus.CONNECTED if distance == 1 else ConnectionStatus.UNKNOWN
        )

    def get_network_distance(self, public_id: str) -> tuple[Classification, int | None]:
        """Degrees of separation: 1 means connected.

        This is how invite acceptance is detected. It is a cheap read against a
        dedicated endpoint rather than a profile fetch, so polling it does not
        burn the view budget or re-notify the prospect.
        """
        classification, payload, _ = self._request(
            "GET", _EP.NETWORK_INFO.format(public_id=public_id)
        )
        if not classification.ok or payload is None:
            return classification, None

        raw = payload.get("distance")
        value = raw.get("value") if isinstance(raw, dict) else raw
        # LinkedIn reports "DISTANCE_1" / "DISTANCE_2" / "OUT_OF_NETWORK" / "SELF".
        mapping = {"SELF": 0, "DISTANCE_1": 1, "DISTANCE_2": 2, "DISTANCE_3": 3}
        if isinstance(value, str):
            if value in mapping:
                return classification, mapping[value]
            return (
                Classification(
                    ResponseClass.UNKNOWN_SHAPE, detail=f"unknown distance value {value!r}"
                ),
                None,
            )
        if isinstance(value, int):
            return classification, value
        return (
            Classification(ResponseClass.UNKNOWN_SHAPE, detail="networkinfo had no distance"),
            None,
        )

    def search_people(self, keywords: str, start: int = 0, count: int = 10) -> SearchPage:
        classification, payload, _ = self._request(
            "GET",
            _EP.SEARCH_BLENDED,
            params={
                "keywords": keywords,
                "origin": "GLOBAL_SEARCH_HEADER",
                "q": "all",
                "start": start,
                "count": count,
                "filters": "List(resultType->PEOPLE)",
                "queryContext": "List(spellCorrectionEnabled->true)",
            },
        )
        if not classification.ok or payload is None:
            return SearchPage(profiles=[], classification=classification)

        profiles: list[ProfileSnapshot] = []
        for cluster in payload.get("elements", []):
            for item in cluster.get("elements", []):
                hit = item.get("hitInfo", {})
                # The hit is keyed by a fully-qualified union type name that
                # varies by result kind, so it is matched rather than indexed.
                person: dict[str, Any] = next(
                    (v for k, v in hit.items() if k.endswith("SearchHit") or "Profile" in k),
                    {},
                )
                mini = person.get("miniProfile") or person
                if not mini.get("publicIdentifier"):
                    continue
                profiles.append(
                    ProfileSnapshot(
                        urn=str(mini.get("entityUrn", "")),
                        public_id=str(mini.get("publicIdentifier", "")),
                        first_name=str(mini.get("firstName", "")),
                        last_name=str(mini.get("lastName", "")),
                        headline=str(mini.get("occupation", "")),
                        raw=mini,
                    )
                )

        return SearchPage(
            profiles=profiles,
            total=int(payload.get("paging", {}).get("total", len(profiles))),
            next_start=start + count if profiles else None,
            classification=classification,
        )

    @staticmethod
    def _parse_event(event: dict[str, Any], me_urn: str) -> MessageEvent:
        """One entry from a thread's `events` array."""
        sender = (event.get("from") or {}).get(
            "com.linkedin.voyager.messaging.MessagingMember", {}
        )
        sender_mini = sender.get("miniProfile") or {}

        event_content = (event.get("eventContent") or {}).get(
            "com.linkedin.voyager.messaging.event.MessageEvent", {}
        )
        attributed = event_content.get("attributedBody") or {}
        text = str(attributed.get("text", event_content.get("body", "")))

        timestamp = event.get("createdAt")
        sent_at = (
            datetime.fromtimestamp(timestamp / 1000, tz=UTC)
            if isinstance(timestamp, (int, float))
            else None
        )

        return MessageEvent(
            event_urn=str(event.get("entityUrn", "") or event.get("dashEntityUrn", "")),
            from_me=bool(me_urn and sender_mini.get("entityUrn") == me_urn),
            text=text,
            sent_at=sent_at,
        )

    def list_conversations(
        self, limit: int = 20
    ) -> tuple[Classification, list[ConversationSnapshot]]:
        """Recent threads. This is what reply detection polls.

        Each thread element already carries a short `events` array (its
        recent messages, not full history) — parsed into `MessageEvent`s so
        the inbox has some backlog beyond just the latest message.
        """
        classification, payload, _ = self._request(
            "GET",
            _EP.CONVERSATIONS,
            params={"keyVersion": "LEGACY_INBOX", "count": limit},
        )
        if not classification.ok or payload is None:
            return classification, []

        me_urn = ""
        conversations: list[ConversationSnapshot] = []

        for element in payload.get("elements", []):
            raw_events = element.get("events") or []
            events = [self._parse_event(e, me_urn) for e in raw_events]
            last = events[0] if events else MessageEvent()

            participants = element.get("participants") or []
            other = next(
                (
                    (p.get("com.linkedin.voyager.messaging.MessagingMember") or {}).get(
                        "miniProfile"
                    )
                    or {}
                    for p in participants
                ),
                {},
            )

            timestamp = element.get("lastActivityAt")
            last_activity = (
                datetime.fromtimestamp(timestamp / 1000, tz=UTC)
                if isinstance(timestamp, (int, float))
                else None
            )

            conversations.append(
                ConversationSnapshot(
                    conversation_urn=str(element.get("entityUrn", "")),
                    participant_urn=str(other.get("entityUrn", "")),
                    participant_name=(
                        f"{other.get('firstName', '')} {other.get('lastName', '')}".strip()
                    ),
                    last_activity_at=last_activity,
                    last_message_text=last.text,
                    # Whose message was last decides whether a sequence stops.
                    last_message_from_me=last.from_me
                    or bool(element.get("read", False) and not element.get("unreadCount")),
                    unread=bool(element.get("unreadCount", 0)),
                    raw=element,
                    events=events,
                )
            )

        return classification, conversations

    # ── writes ───────────────────────────────────────────────────────────────

    def send_invitation(self, profile_urn: str, note: str = "") -> ActionResult:
        """Send a connection request, with an optional note.

        Tries the current relationships endpoint first and falls back to the
        legacy one, because LinkedIn rolls these changes out per-account.
        """
        profile_id = extract_profile_id(profile_urn)

        dash_body: dict[str, Any] = {"inviteeProfileUrn": f"urn:li:fsd_profile:{profile_id}"}
        if note:
            dash_body["customMessage"] = note

        classification, payload, _ = self._request(
            "POST",
            _EP.INVITE_DASH,
            params={"action": "verifyQuotaAndCreateV2"},
            json={"invitee": dash_body},
            headers={"Content-Type": "application/json"},
        )

        if classification.ok:
            return ActionResult(
                classification=classification,
                remote_id=str((payload or {}).get("value", {}).get("entityUrn", "")),
                payload=payload or {},
            )

        # A shape error here means this account is on the older endpoint.
        if classification.response_class in {
            ResponseClass.UNKNOWN_SHAPE,
            ResponseClass.NOT_FOUND,
        }:
            legacy_body = {
                "trackingId": str(uuid.uuid4()),
                "message": note,
                "invitations": [],
                "excludeInvitations": [],
                "invitee": {
                    "com.linkedin.voyager.growth.invitation.InviteeProfile": {
                        "profileId": profile_id
                    }
                },
            }
            legacy_class, legacy_payload, _ = self._request(
                "POST",
                _EP.INVITE_LEGACY,
                json=legacy_body,
                headers={"Content-Type": "application/json"},
            )
            return ActionResult(
                classification=legacy_class,
                remote_id=str((legacy_payload or {}).get("entityUrn", "")),
                payload=legacy_payload or {},
            )

        return ActionResult(classification=classification, payload=payload or {})

    def withdraw_invitation(self, invitation_urn: str) -> ActionResult:
        """Withdraw a pending invite.

        Run on a schedule against invites older than ~3 weeks: a large pending
        pile depresses acceptance rate and is itself a flag on the account.
        """
        invitation_id = extract_profile_id(invitation_urn)
        classification, payload, _ = self._request(
            "POST",
            _EP.INVITE_WITHDRAW.format(invitation_id=invitation_id),
            params={"action": "withdraw"},
            json={},
            headers={"Content-Type": "application/json"},
        )
        return ActionResult(classification=classification, payload=payload or {})

    def send_message(self, profile_urn: str, text: str) -> ActionResult:
        profile_id = extract_profile_id(profile_urn)
        body = {
            "keyVersion": "LEGACY_INBOX",
            "conversationCreate": {
                "eventCreate": {
                    "value": {
                        "com.linkedin.voyager.messaging.create.MessageCreate": {
                            "body": text,
                            "attachments": [],
                            "attributedBody": {"text": text, "attributes": []},
                            "mediaAttachments": [],
                        }
                    }
                },
                "recipients": [profile_id],
                "subtype": "MEMBER_TO_MEMBER",
            },
        }
        classification, payload, _ = self._request(
            "POST",
            _EP.CONVERSATIONS,
            params={"action": "create"},
            json=body,
            headers={"Content-Type": "application/json"},
        )
        return ActionResult(
            classification=classification,
            remote_id=str((payload or {}).get("value", {}).get("eventUrn", "")),
            payload=payload or {},
        )

    def warm_session(self) -> Classification:
        """Read the feed the way an opening app would.

        A session whose very first request is a write looks nothing like a human
        opening LinkedIn. Called before the first action of a dispatch window.
        """
        classification, _, _ = self._request(
            "GET", _EP.FEED, params={"count": 10, "q": "chronFeed"}
        )
        return classification

    # ── lifecycle ────────────────────────────────────────────────────────────

    @property
    def session(self) -> SessionBundle | None:
        return self._session

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> MobileVoyagerDriver:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
