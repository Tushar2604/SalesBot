"""Browser-backed LinkedIn driver: every action runs inside a real Chromium.

The httpx Voyager driver replays cookies minted in a browser from a client whose
TLS and header fingerprint is nothing like one, and LinkedIn answers the first
real action with a redirect to login. This driver instead performs each action
the way a person does — open the profile, click Connect, type the note, click
Send — inside a headed Chromium (under Xvfb) that carries the account's frozen
desktop identity, its proxy, and the cookies from the remote-browser login.

Scope: connect, profile view, invite with a note, message, acceptance check.
Reply polling, people search and invite withdrawal are not implemented; each
says so rather than returning fabricated data.

Selectors are role/text based rather than CSS-class based because LinkedIn's
class names are generated. When a step cannot find its element the driver saves
a screenshot under `debug_screens/` and reports UNKNOWN_SHAPE, so a change on
LinkedIn's side is a one-line selector fix rather than a mystery.

Playwright's sync API is used: Celery tasks are synchronous.
"""

from __future__ import annotations

import random
import re
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from app.core.logging import get_logger
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
from app.linkedin.remote_browser import browser_fingerprint

if TYPE_CHECKING:
    from playwright.sync_api import BrowserContext, Locator, Page

log = get_logger(__name__)

BASE: Final[str] = "https://www.linkedin.com"
DEBUG_DIR: Final[Path] = Path("/srv/debug_screens")

_LOGIN_URL_MARKERS: Final[tuple[str, ...]] = ("/login", "/authwall", "/uas/login", "/signup")
_DEGREE_RE = re.compile(r"\b(1st|2nd|3rd)\b")
_DEGREE_VALUE = {"1st": 1, "2nd": 2, "3rd": 3}

# Inbox scraping. Read from the messaging page LinkedIn itself renders.
_MAX_THREADS_PER_POLL = 3
_TIME_RE = re.compile(r"\b(\d{1,2}:\d{2}\s?[AP]M)\b", re.I)
_THREAD_RE = re.compile(r"/messaging/thread/([^/?#]+)")
_MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

# The profile's own top card (the section holding the name), not the whole page:
# "People you may know" further down is full of Connect buttons for other people.
_TOP_CARD_JS = r"""
() => {
  // The profile's own top card (name, degree, actions). Anchored on the "Contact
  // info" link, which only that card has; the name heading is the fallback.
  const contact = document.querySelector('main a[href*="contact-info"]');
  const heading = Array.from(document.querySelectorAll('main h1, main h2'))
    .find(e => !/notification/i.test(e.innerText));
  const anchor = contact || heading;
  const card = anchor ? (anchor.closest('section') || anchor.parentElement) : null;
  if (!card) return null;
  const clean = (t) => (t || '').trim().replace(/\s+/g, ' ');
  return {
    text: clean(card.innerText).slice(0, 1500),
    buttons: Array.from(card.querySelectorAll('button, a'))
      .map(b => clean(b.innerText)).filter(t => t && t.length < 40),
    labels: Array.from(card.querySelectorAll('[aria-label]'))
      .map(e => clean(e.getAttribute('aria-label'))).filter(Boolean).slice(0, 40),
  };
}
"""

_ROWS_JS = """
() => Array.from(document.querySelectorAll('li.msg-conversation-listitem')).map((li, i) => ({
  i,
  name: ((li.querySelector('[class*="participant-names"]') || {}).innerText || '').trim(),
  unread: !!li.querySelector('[class*="unread"]'),
  active: !!li.querySelector('[class*="link--active"]'),
}))
"""

_EVENTS_JS = """
() => {
  const out = [];
  let heading = '';
  document.querySelectorAll('ul[class*="msg-s-message-list-content"] > li').forEach(li => {
    const events = li.querySelectorAll('[data-event-urn]');
    if (!events.length) {
      const t = (li.innerText || '').trim();
      if (t && t.length < 24) heading = t;
      return;
    }
    events.forEach(e => {
      const body = e.querySelector('.msg-s-event-listitem__body');
      out.push({
        urn: e.getAttribute('data-event-urn'),
        // LinkedIn marks the other person's messages with --other. The sender
        // id inside the urn is the thread owner's for every message, so it
        // cannot tell the two sides apart.
        other: e.classList.contains('msg-s-event-listitem--other'),
        body: body ? body.innerText.trim() : '',
        text: e.innerText || '',
        heading,
      });
    });
  });
  return out;
}
"""

# Chromium flags a container needs. Deliberately no automation-masking patches:
# this browser is honestly an automated one, driven at human pace.
_LAUNCH_ARGS: Final[list[str]] = ["--no-sandbox", "--disable-dev-shm-usage"]


def _read_connection_status(card: dict[str, Any] | None) -> ConnectionStatus:
    """Classifies a profile top card. Anything ambiguous is UNKNOWN, never a guess."""
    if not card:
        return ConnectionStatus.UNKNOWN
    text = str(card.get("text") or "")
    buttons = [str(b).strip().lower() for b in card.get("buttons") or []]
    labels = [str(a).strip().lower() for a in card.get("labels") or []]

    if re.search(r"\b1st\b", text):
        return ConnectionStatus.CONNECTED
    if any(b == "pending" for b in buttons) or any(a.startswith("pending") for a in labels):
        return ConnectionStatus.PENDING
    # Only a visible Connect action proves there is no invite waiting. "Follow"
    # alone (some profiles hide Connect under "More") proves nothing.
    if any(b == "connect" for b in buttons) or any(
        a.startswith("invite ") and a.endswith(" to connect") for a in labels
    ):
        return ConnectionStatus.NOT_CONNECTED
    return ConnectionStatus.UNKNOWN


class _StepFailed(Exception):
    """A UI step could not find its element. Carries the classification to return."""

    def __init__(self, classification: Classification) -> None:
        super().__init__(classification.detail)
        self.classification = classification


def _unknown(detail: str) -> Classification:
    return Classification(ResponseClass.UNKNOWN_SHAPE, detail=detail)


class BrowserDriver:
    """One instance per account, per unit of work. Not thread-safe by design."""

    def __init__(
        self,
        *,
        fingerprint: dict[str, Any],
        proxy_url: str | None = None,
        session: SessionBundle | None = None,
        timeout: float = 30.0,
        timezone: str = "UTC",
    ) -> None:
        self._browser_fp: dict[str, Any] = fingerprint.get(
            "browser"
        ) or browser_fingerprint.generate(timezone=timezone)
        self._proxy_url = proxy_url
        self._session = session
        self._timeout_ms = int(timeout * 1000)
        self._pw: Any = None
        self._browser: Any = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    # ── plumbing ─────────────────────────────────────────────────────────────

    def _ensure_page(self) -> Page:
        if self._page is not None:
            return self._page

        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        launch: dict[str, Any] = {"headless": False, "args": _LAUNCH_ARGS}
        if self._proxy_url:
            parts = urlsplit(self._proxy_url)
            proxy: dict[str, str] = {"server": f"{parts.scheme}://{parts.hostname}:{parts.port}"}
            if parts.username:
                proxy["username"] = parts.username
            if parts.password:
                proxy["password"] = parts.password
            launch["proxy"] = proxy

        self._browser = self._pw.chromium.launch(**launch)
        self._context = self._browser.new_context(
            viewport=dict(browser_fingerprint.viewport(self._browser_fp)),
            user_agent=browser_fingerprint.user_agent(self._browser_fp),
            locale=self._browser_fp.get("locale", "en-US"),
            timezone_id=self._browser_fp.get("timezone", "UTC"),
        )
        if self._session is not None:
            self._context.add_cookies(
                [
                    {
                        "name": name,
                        "value": value,
                        "domain": ".linkedin.com",
                        "path": "/",
                        "secure": True,
                    }
                    for name, value in self._session.cookies.items()
                ]
            )
        self._page = self._context.new_page()
        self._page.set_default_timeout(self._timeout_ms)
        return self._page

    @staticmethod
    def _pause(low: float, high: float, page: Page | None = None) -> None:
        seconds = random.uniform(low, high)  # noqa: S311 - pacing, not security
        if page is not None:
            page.wait_for_timeout(seconds * 1000)
        else:
            time.sleep(seconds)

    def _type(self, page: Page, text: str) -> None:
        """Types in short bursts with uneven delays, as a person does."""
        index = 0
        while index < len(text):
            burst = random.randint(2, 6)  # noqa: S311
            page.keyboard.type(text[index : index + burst], delay=random.uniform(55, 150))  # noqa: S311
            index += burst
            if random.random() < 0.15:  # noqa: S311
                self._pause(0.2, 0.7, page)

    def _screenshot(self, label: str) -> None:
        if self._page is None:
            return
        try:
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            self._page.screenshot(path=str(DEBUG_DIR / f"{stamp}-{label}.png"))
        except Exception:
            log.warning("linkedin.browser.screenshot_failed", label=label)

    def _classify_page(self, page: Page, status: int | None) -> Classification:
        """Reduces where the browser landed to a safety class.

        Only the URL, the title and alert/modal text are examined — never the
        whole page body, because a prospect's own headline containing a phrase
        like "unusual activity" must not read as an account restriction.
        """
        url = page.url.lower()
        if "checkpoint" in url:
            return Classification(
                ResponseClass.CHALLENGE,
                detail="redirected to a LinkedIn checkpoint",
                challenge_url=page.url,
            )
        if any(marker in url for marker in _LOGIN_URL_MARKERS):
            return Classification(
                ResponseClass.AUTH_LOST, detail="LinkedIn sent the browser to its login page"
            )
        try:
            alerts = " ".join(
                page.locator(
                    "[role=alert], [role=alertdialog], .artdeco-toast-item"
                ).all_inner_texts()
            )
            text = f"{page.title()} {alerts}"
        except Exception:
            text = ""
        result = classify_response(
            status_code=status or 200, body=text[:4000], final_url=page.url, payload={}
        )
        return result

    def _goto(self, path_or_url: str) -> tuple[Page, Classification]:
        page = self._ensure_page()
        url = path_or_url if path_or_url.startswith("http") else f"{BASE}{path_or_url}"
        try:
            response = page.goto(url, wait_until="domcontentloaded")
        except Exception as exc:
            name = type(exc).__name__
            return page, Classification(
                ResponseClass.TRANSPORT_ERROR, detail=f"{name}: {exc}"[:300]
            )
        self._pause(1.5, 3.5, page)
        return page, self._classify_page(page, response.status if response else None)

    def _on_profile(self, public_id: str) -> tuple[Page, Classification]:
        """Opens a profile, unless the browser is already on it (no double view)."""
        page = self._ensure_page()
        if f"/in/{public_id.lower()}" in page.url.lower():
            return page, Classification(ResponseClass.OK)
        return self._goto(f"/in/{public_id}/")

    def _scroll_like_reading(self, page: Page, passes: int = 3) -> None:
        for _ in range(passes):
            page.mouse.wheel(0, random.randint(250, 650))  # noqa: S311
            self._pause(0.8, 2.2, page)

    # ── authentication ───────────────────────────────────────────────────────

    def authenticate_with_cookie(
        self,
        li_at: str,
        jsessionid: str | None = None,
        cookies: dict[str, str] | None = None,
    ) -> AuthResult:
        """Adopt the cookies from the remote-browser login and prove they work.

        `cookies` is the full LinkedIn cookie set from that browser; a session
        carrying only `li_at` is missing the identifiers a real browser has.
        """
        jar = dict(cookies or {})
        jar["li_at"] = li_at.strip()
        if jsessionid:
            jar["JSESSIONID"] = f'"{jsessionid.strip(chr(34))}"'
        self.close()
        self._session = SessionBundle(
            cookies=jar,
            csrf_token=jar.get("JSESSIONID", "").strip('"'),
            established_at=datetime.now(UTC),
        )

        classification, profile = self.verify_session()
        if not classification.ok or profile is None:
            self._session = None
            return AuthResult(classification=classification)
        return AuthResult(classification=classification, session=self._session)

    def authenticate_with_credentials(self, email: str, password: str) -> AuthResult:
        return AuthResult(
            classification=_unknown(
                "email/password sign-in is not supported: use the remote-browser sign-in"
            )
        )

    def submit_challenge(self, challenge: ChallengeContext, code: str) -> AuthResult:
        return AuthResult(
            classification=_unknown("complete verification in the remote-browser sign-in")
        )

    def verify_session(self) -> tuple[Classification, ProfileSnapshot | None]:
        # One page load: /in/me/ redirects to the signed-in member's own profile,
        # which both proves the session and says who it belongs to.
        page, classification = self._goto("/in/me/")
        if not classification.ok:
            return classification, None

        match = re.search(r"/in/([^/?#]+)", page.url)
        if not match or match.group(1) == "me":
            self._screenshot("verify-no-profile")
            return _unknown("could not resolve the signed-in profile from /in/me/"), None
        return classification, self._read_profile(page, match.group(1))

    # ── reads ────────────────────────────────────────────────────────────────

    @staticmethod
    def _profile_name(page: Page) -> str:
        """The member's name from the tab title ("(1) Jane Doe | LinkedIn")."""
        title = re.sub(r"^\(\d+\)\s*", "", page.title())
        return title.split("|")[0].strip()

    def _read_profile(self, page: Page, public_id: str) -> ProfileSnapshot:
        full_name = self._profile_name(page)
        headline = ""
        try:
            headline = page.locator("main .text-body-medium").first.inner_text(timeout=2000).strip()
        except Exception:
            log.info("linkedin.browser.headline_missing", public_id=public_id)
        first, _, last = full_name.partition(" ")
        # The "urn" the rest of the system stores is the public id: the browser
        # addresses people by /in/<id>/, and never needs LinkedIn's internal urn.
        return ProfileSnapshot(
            urn=public_id,
            public_id=public_id,
            first_name=first,
            last_name=last,
            headline=headline,
        )

    def get_profile(self, public_id: str) -> tuple[Classification, ProfileSnapshot | None]:
        page, classification = self._on_profile(public_id)
        if not classification.ok:
            return classification, None
        return classification, self._read_profile(page, public_id)

    def view_profile(self, public_id: str) -> ActionResult:
        page, classification = self._on_profile(public_id)
        if not classification.ok:
            return ActionResult(classification=classification)
        self._scroll_like_reading(page)
        self._pause(2.0, 6.0, page)
        return ActionResult(classification=classification, remote_id=public_id)

    def get_network_distance(self, public_id: str) -> tuple[Classification, int | None]:
        page, classification = self._on_profile(public_id)
        if not classification.ok:
            return classification, None
        try:
            top_card = page.locator("main").first.inner_text(timeout=4000)[:1500]
        except Exception:
            return classification, None
        match = _DEGREE_RE.search(top_card)
        return classification, _DEGREE_VALUE[match.group(1)] if match else None

    def get_connection_status(
        self, public_id: str
    ) -> tuple[Classification, ConnectionStatus]:
        page, classification = self._on_profile(public_id)
        if not classification.ok:
            return classification, ConnectionStatus.UNKNOWN
        try:
            card = page.evaluate(_TOP_CARD_JS)
        except Exception:
            return classification, ConnectionStatus.UNKNOWN
        return classification, _read_connection_status(card)

    def search_people(self, keywords: str, start: int = 0, count: int = 10) -> SearchPage:
        return SearchPage(
            profiles=[],
            classification=_unknown("people search is not supported by this driver"),
        )

    def _heading_date(self, heading: str, today: date) -> date:
        """Turns the thread's day divider ("TODAY", "Sep 17", "MONDAY") into a date."""
        h = heading.strip().lower()
        if not h or h == "today":
            return today
        if h == "yesterday":
            return today - timedelta(days=1)
        if h in _WEEKDAYS:
            back = (today.weekday() - _WEEKDAYS.index(h)) % 7 or 7
            return today - timedelta(days=back)
        match = re.match(r"([a-z]{3})[a-z]*\s+(\d{1,2})(?:,?\s+(\d{4}))?", h)
        if match and match.group(1) in _MONTHS:
            year = int(match.group(3)) if match.group(3) else today.year
            try:
                found = date(year, _MONTHS[match.group(1)], int(match.group(2)))
            except ValueError:
                return today
            return found - timedelta(days=365) if found > today and not match.group(3) else found
        return today

    def _read_open_thread(
        self, page: Page, row_name: str, unread: bool
    ) -> ConversationSnapshot | None:
        """Reads the thread currently open in the messaging pane."""
        thread = _THREAD_RE.search(page.url)
        header = page.locator('a[href*="/in/ACo"]').first
        if thread is None or not header.count():
            return None  # a LinkedIn notice or ad, not a person-to-person thread
        participant = (header.get_attribute("href") or "").rstrip("/").rsplit("/", 1)[-1]

        zone = ZoneInfo(str(self._browser_fp.get("timezone", "UTC")))
        today = datetime.now(zone).date()
        raw_events: list[dict[str, Any]] = page.evaluate(_EVENTS_JS)

        events: list[MessageEvent] = []
        last_time = ""
        for raw in raw_events:
            time_match = _TIME_RE.search(raw["text"])
            last_time = time_match.group(1) if time_match else last_time
            sent_at: datetime | None = None
            if last_time:
                day = self._heading_date(raw["heading"], today)
                try:
                    clock = datetime.strptime(last_time.upper().replace(" ", ""), "%I:%M%p")
                    sent_at = datetime.combine(day, clock.time(), tzinfo=zone).astimezone(UTC)
                except ValueError:
                    sent_at = None
            events.append(
                MessageEvent(
                    event_urn=raw["urn"],
                    from_me=not raw["other"],
                    text=raw["body"],
                    sent_at=sent_at,
                )
            )
        if not events:
            return None

        newest = events[-1]
        return ConversationSnapshot(
            conversation_urn=thread.group(1),
            participant_urn=participant,
            participant_name=row_name,
            last_activity_at=newest.sent_at,
            last_message_text=newest.text,
            last_message_from_me=newest.from_me,
            unread=unread,
            events=list(reversed(events)),
        )

    @staticmethod
    def _inbox_is_empty(page: Page) -> bool:
        """True when LinkedIn is showing its "No messages yet" empty state."""
        try:
            body = page.locator("body").inner_text(timeout=2000)
        except Exception:
            return False
        return "no messages yet" in body.lower()

    def list_conversations(
        self, limit: int = 20
    ) -> tuple[Classification, list[ConversationSnapshot]]:
        """Reads the inbox the way a person checks it.

        /messaging/ opens the newest thread on its own, which is where a reply
        or one of our own sends shows up. Any other unread thread is opened with
        a click (a client-side navigation, not another page load), up to a small
        cap. Opening a thread marks it read on LinkedIn, as it would for its owner.
        """
        page, classification = self._goto("/messaging/")
        if not classification.ok:
            return classification, []
        try:
            page.locator("li.msg-conversation-listitem").first.wait_for(timeout=12000)
        except Exception:
            # A brand-new account has an empty inbox. That is a fine state, not a
            # failure: reporting it as one tripped the error-streak breaker and
            # paused the whole account.
            if self._inbox_is_empty(page):
                return classification, []
            self._screenshot("inbox-no-list")
            return _unknown("messaging page showed no conversation list"), []

        rows: list[dict[str, Any]] = page.evaluate(_ROWS_JS)
        snapshots: list[ConversationSnapshot] = []
        opened = 0
        for row in rows[: max(1, limit)]:
            if not row["active"]:
                if not row["unread"] or opened >= _MAX_THREADS_PER_POLL - 1:
                    continue
                self._pause(0.8, 2.0, page)
                page.locator("li.msg-conversation-listitem").nth(row["i"]).click()
                self._pause(1.8, 3.2, page)
                opened += 1
            try:
                snapshot = self._read_open_thread(page, row["name"], row["unread"])
            except Exception:
                log.warning("linkedin.browser.thread_read_failed", row=row["i"])
                self._screenshot("inbox-thread-error")
                continue
            if snapshot is not None:
                snapshots.append(snapshot)
        return Classification(ResponseClass.OK), snapshots

    def warm_session(self) -> Classification:
        page, classification = self._goto("/feed/")
        if classification.ok:
            self._scroll_like_reading(page, passes=random.randint(2, 4))  # noqa: S311
        return classification

    # ── writes ───────────────────────────────────────────────────────────────

    def _in_main_column(self, page: Page, element: Any) -> bool:
        """True when the element is in the profile's own column, not the
        "More profiles for you" sidebar, whose buttons belong to other people."""
        box = element.bounding_box()
        if box is None:
            return False
        width = page.viewport_size["width"] if page.viewport_size else 1440
        return bool(box["x"] + box["width"] / 2 < width * 0.62)

    def _main_column_button(self, page: Page, pattern: str) -> Any:
        """First visible button or link matching `pattern` in the profile's column."""
        rx = re.compile(pattern, re.I)
        for role in ("button", "link"):
            found = page.get_by_role(role, name=rx)
            for i in range(found.count()):
                item = found.nth(i)
                if item.is_visible() and self._in_main_column(page, item):
                    return item
        return None

    def _find_connect(self, page: Page, public_id: str) -> Any:
        """The Connect control for *this* profile only.

        The top card's Connect is a link to `/preload/custom-invite/?vanityName=<id>`.
        Matching on that id is what keeps a click from ever landing on one of the
        sidebar's "Invite <someone else> to connect" buttons.
        """
        links = page.locator(f'a[href*="vanityName={public_id}"][aria-label^="Invite"]')
        visible = [links.nth(i) for i in range(links.count()) if links.nth(i).is_visible()]
        # Prefer the top card's own button over the sticky-header copy.
        for link in visible:
            if self._in_main_column(page, link):
                return link
        if visible:
            return visible[0]

        # Fall back to the More menu, where LinkedIn tucks Connect for some profiles.
        more = self._main_column_button(page, r"^More( actions)?$")
        if more is not None:
            more.click()
            self._pause(0.6, 1.4, page)
            menu = page.locator(f'[role=menu] a[href*="vanityName={public_id}"]')
            if menu.count():
                return menu.first
        return None

    @staticmethod
    def _settle(page: Page, timeout_ms: int = 6000) -> None:
        """Waits, best effort, for the page to stop loading before it is clicked.

        LinkedIn keeps a background connection open, so "idle" may never arrive;
        the timeout makes this a courtesy, not a gate.
        """
        try:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
        except Exception:
            log.info("linkedin.browser.page_not_idle", url=page.url)

    def _wait_invite_dialog(self, page: Page, dialog: Locator, seconds: float) -> str:
        """The invitation prompt's text once it appears, or "" if it never does."""
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if dialog.count():
                try:
                    text = dialog.inner_text(timeout=1500).lower()
                except Exception:
                    text = ""
                if "invit" in text or "note" in text:
                    return text
            page.wait_for_timeout(500)
        return ""

    def send_invitation(self, profile_urn: str, note: str = "") -> ActionResult:
        public_id = profile_urn
        page, classification = self._on_profile(public_id)
        if not classification.ok:
            return ActionResult(classification=classification)

        try:
            if self._main_column_button(page, r"^Pending"):
                return ActionResult(
                    classification=classification,
                    remote_id=public_id,
                    payload={"already": "pending"},
                )

            connect = self._find_connect(page, public_id)
            if connect is None:
                self._screenshot("invite-no-connect")
                return ActionResult(
                    classification=Classification(
                        ResponseClass.NOT_FOUND,
                        detail="no Connect option (already connected, or follow-only)",
                    )
                )
            # The link navigates to /preload/custom-invite/ and the modal loads
            # after it; wait for the invitation prompt itself rather than assume.
            dialog = page.locator("dialog[open], [role=dialog]").last
            dialog_text = ""
            self._settle(page)
            for attempt in range(2):
                if attempt:
                    # The first click did nothing: the page had not finished loading,
                    # so its buttons were not wired up yet. Let it settle, then retry.
                    log.info("linkedin.browser.invite_retry_click", url=page.url)
                    self._settle(page, timeout_ms=15000)
                    self._pause(2.0, 4.0, page)
                    connect = self._find_connect(page, public_id)
                    if connect is None:
                        break
                connect.scroll_into_view_if_needed()
                connect.hover()
                self._pause(0.4, 1.1, page)
                connect.click()
                self._pause(1.5, 2.8, page)
                dialog_text = self._wait_invite_dialog(page, dialog, seconds=10)
                if dialog_text:
                    break
            # Never press anything in a dialog that is not the invitation prompt.
            if not dialog_text:
                log.warning(
                    "linkedin.browser.invite_dialog_missing",
                    url=page.url,
                    dialogs=page.locator("dialog[open], [role=dialog]").count(),
                )
                self._screenshot("invite-unexpected-dialog")
                raise _StepFailed(_unknown("invite click did not open the invitation dialog"))

            note_sent = False
            if note:
                add_note = dialog.get_by_role("button", name=re.compile(r"^Add a note$", re.I))
                if add_note.count():
                    add_note.first.click()
                    self._pause(0.7, 1.5, page)
                    box = dialog.locator("textarea")
                    if box.count():
                        box.first.click()
                        self._type(page, note[:300])
                        note_sent = True
                    # No textarea: the account is out of personalised notes.
                    # Fall through and send without one rather than fail.

            self._pause(0.8, 2.0, page)
            send = dialog.get_by_role("button", name=re.compile(r"^Send( invitation| now)?$", re.I))
            if not send.count():
                send = dialog.get_by_role("button", name=re.compile(r"^Send without a note$", re.I))
            if not send.count():
                self._screenshot("invite-no-send")
                raise _StepFailed(_unknown("invite dialog had no Send button"))
            send.first.click()
            self._pause(2.0, 3.5, page)

            after = self._classify_page(page, None)
            if not after.ok:
                return ActionResult(classification=after)

            # Confirm it took: the profile must now show Pending, not Connect.
            page.goto(f"{BASE}/in/{public_id}/", wait_until="domcontentloaded")
            self._pause(1.5, 3.0, page)
            if self._find_connect(page, public_id) is not None:
                self._screenshot("invite-not-confirmed")
                return ActionResult(
                    classification=_unknown("Send was clicked but the profile still offers Connect")
                )
            return ActionResult(
                classification=Classification(ResponseClass.OK),
                remote_id=public_id,
                payload={"note_sent": note_sent, "note_requested": bool(note)},
            )
        except _StepFailed as exc:
            return ActionResult(classification=exc.classification)
        except Exception as exc:
            self._screenshot("invite-error")
            return ActionResult(
                classification=_unknown(f"invite step failed: {type(exc).__name__}")
            )

    def send_message(self, profile_urn: str, text: str) -> ActionResult:
        public_id = profile_urn
        page, classification = self._on_profile(public_id)
        if not classification.ok:
            return ActionResult(classification=classification)

        try:
            name = self._profile_name(page)
            button = self._main_column_button(page, r"^Message")
            if button is None:
                return ActionResult(
                    classification=Classification(
                        ResponseClass.NOT_FOUND, detail="no Message option: not a connection yet"
                    )
                )
            label = (button.get_attribute("aria-label") or "").strip().lower()
            if label not in ("", "message") and name.lower() not in label:
                # A Message control that names somebody else.
                self._screenshot("message-wrong-person")
                return ActionResult(classification=_unknown("Message control names another member"))
            href = button.get_attribute("href") or ""
            if not href.startswith("/messaging/compose/"):
                self._screenshot("message-unexpected-link")
                return ActionResult(
                    classification=_unknown("Message control is not a compose link")
                )

            # The overlay the link normally opens is script-driven and does not open
            # reliably here; the link's own target is the full compose page for the
            # same recipient, so open that instead.
            self._pause(0.6, 1.4, page)
            page.goto(f"{BASE}{href}", wait_until="domcontentloaded")
            self._pause(2.5, 4.5, page)

            box = page.locator("[role=textbox][contenteditable=true]").last
            box.wait_for(state="visible", timeout=15000)
            # Only type into a compose page that is actually addressed to this member.
            if name and name.lower() not in page.locator("main").first.inner_text().lower():
                self._screenshot("message-recipient-mismatch")
                return ActionResult(
                    classification=_unknown("compose page does not show the intended recipient")
                )
            box.click()
            self._type(page, text)
            self._pause(0.8, 2.0, page)

            send = page.get_by_role("button", name=re.compile(r"^Send$", re.I)).last
            if not send.is_enabled():
                self._screenshot("message-send-disabled")
                return ActionResult(classification=_unknown("Send stayed disabled after typing"))
            send.click()
            self._pause(2.0, 3.5, page)

            if box.inner_text().strip():
                self._screenshot("message-not-sent")
                return ActionResult(classification=_unknown("message box not cleared after Send"))
            # LinkedIn's member id for this person, from the compose link. It is the
            # only stable bridge between a lead (stored by vanity slug) and the
            # inbox, which identifies participants by member id.
            member_id = parse_qs(urlsplit(href).query).get("recipient", [""])[0]
            return ActionResult(
                classification=Classification(ResponseClass.OK),
                remote_id=public_id,
                payload={"member_id": member_id} if member_id else {},
            )
        except Exception as exc:
            self._screenshot("message-error")
            return ActionResult(
                classification=_unknown(f"message step failed: {type(exc).__name__}")
            )

    def withdraw_invitation(self, invitation_urn: str) -> ActionResult:
        return ActionResult(
            classification=_unknown(
                "withdrawing invitations is not supported by the browser driver"
            )
        )

    # ── lifecycle ────────────────────────────────────────────────────────────

    @property
    def session(self) -> SessionBundle | None:
        return self._session

    def close(self) -> None:
        for target, method in (
            (self._context, "close"),
            (self._browser, "close"),
            (self._pw, "stop"),
        ):
            if target is None:
                continue
            try:
                getattr(target, method)()
            except Exception:
                log.warning("linkedin.browser.close_failed")
        self._page = self._context = self._browser = self._pw = None

    def __enter__(self) -> BrowserDriver:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
