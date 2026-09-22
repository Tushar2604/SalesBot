"""Owns the lifecycle of every live remote-browser login session.

Deliberately not a Celery task (see the plan this implements): a live,
human-paced session is held by an `asyncio.Task` for as long as its WebSocket
connection is open, in this process, not queued and time-limited the way an
ordinary background job is. One `RemoteBrowserManager` singleton tracks every
session currently open on this process.
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import redis.asyncio as aioredis
from sqlalchemy import select

from app.config import settings
from app.core.logging import get_logger
from app.db import AsyncSessionLocal
from app.linkedin import proxy as proxy_mod
from app.linkedin.remote_browser import browser_fingerprint, stealth, xvfb
from app.linkedin.remote_browser.cdp_relay import CdpRelay
from app.linkedin.remote_browser.playwright_pool import get_playwright, to_playwright_proxy
from app.linkedin.remote_browser.protocol import KeyInput, MouseInput, StatusMessage, StatusState
from app.models.linkedin import LinkedInAccount
from app.scheduler.locks import slot_key
from app.services.linkedin_service import seal_for_transit
from app.worker.celery_app import celery_app

log = get_logger(__name__)

# Slot TTL is renewed on this cadence for as long as the session lives — much
# shorter than scheduler.locks.SLOT_TTL_SECONDS (180s), which assumes a
# request-length hold, not a human-paced one lasting minutes.
_SLOT_HEARTBEAT_SECONDS = 60
_SLOT_TTL_SECONDS = 180
_LOGIN_POLL_SECONDS = 1.5
_AUTHENTICATED_URL_MARKERS = ("linkedin.com/feed", "linkedin.com/mynetwork", "linkedin.com/in/")


class RemoteBrowserError(Exception):
    """Base class for remote-browser session errors, each mapped to a WS close code."""

    close_code: int = 4000


class SlotBusy(RemoteBrowserError):
    close_code = 4001


class TooManyRemoteSessions(RemoteBrowserError):
    close_code = 4002


class LaunchFailed(RemoteBrowserError):
    close_code = 4003


def _redis() -> aioredis.Redis:
    client: aioredis.Redis = aioredis.from_url(  # type: ignore[no-untyped-call]
        settings.redis_url, decode_responses=True
    )
    return client


async def _acquire_slot(account_id: uuid.UUID) -> str:
    client = _redis()
    token = str(uuid.uuid4())
    try:
        if not await client.set(slot_key(account_id), token, nx=True, ex=_SLOT_TTL_SECONDS):
            raise SlotBusy(f"account {account_id} is already acting")
    finally:
        await client.aclose()
    return token


async def _renew_slot(account_id: uuid.UUID, token: str) -> None:
    client = _redis()
    try:
        if await client.get(slot_key(account_id)) == token:
            await client.expire(slot_key(account_id), _SLOT_TTL_SECONDS)
    finally:
        await client.aclose()


async def _release_slot(account_id: uuid.UUID, token: str) -> None:
    client = _redis()
    try:
        if await client.get(slot_key(account_id)) == token:
            await client.delete(slot_key(account_id))
    finally:
        await client.aclose()


@dataclass
class RemoteBrowserSession:
    account_id: uuid.UUID
    workspace_id: uuid.UUID
    browser: object
    context: object
    page: object
    relay: CdpRelay
    slot_token: str
    frame_queue: asyncio.Queue[bytes] = field(default_factory=lambda: asyncio.Queue(maxsize=1))
    status_queue: asyncio.Queue[StatusMessage] = field(default_factory=asyncio.Queue)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_input_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _tasks: list[asyncio.Task[None]] = field(default_factory=list)
    _closed: asyncio.Event = field(default_factory=asyncio.Event)

    def touch(self) -> None:
        self.last_input_at = datetime.now(UTC)

    async def push_status(self, state: StatusState, detail: str = "") -> None:
        await self.status_queue.put(StatusMessage(state=state, detail=detail))

    async def push_frame(self, data: bytes) -> None:
        # Keep only the latest frame: a slow WS consumer should see the newest
        # screen state next, not catch up through a backlog of stale ones.
        if self.frame_queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self.frame_queue.get_nowait()
        await self.frame_queue.put(data)

    async def dispatch_input(self, message: MouseInput | KeyInput) -> None:
        self.touch()
        await self.relay.dispatch_input(message)


class RemoteBrowserManager:
    def __init__(self) -> None:
        self._sessions: dict[str, RemoteBrowserSession] = {}
        self._lock = asyncio.Lock()

    async def start(self, account_id: uuid.UUID, workspace_id: uuid.UUID) -> RemoteBrowserSession:
        async with self._lock:
            if len(self._sessions) >= settings.remote_browser_max_concurrent:
                raise TooManyRemoteSessions("the server is at capacity for live sessions")
            if str(account_id) in self._sessions:
                raise SlotBusy(f"account {account_id} already has a live session")

        slot_token = await _acquire_slot(account_id)
        try:
            session = await self._launch(account_id, workspace_id, slot_token)
        except SlotBusy:
            await _release_slot(account_id, slot_token)
            raise
        except Exception as exc:
            await _release_slot(account_id, slot_token)
            log.warning("remote_browser.launch_failed", account_id=str(account_id), error=str(exc))
            raise LaunchFailed(str(exc)) from exc

        async with self._lock:
            self._sessions[str(account_id)] = session

        session._tasks.append(asyncio.create_task(self._heartbeat_loop(session)))
        session._tasks.append(asyncio.create_task(self._watchdog_loop(session)))
        session._tasks.append(asyncio.create_task(self._login_poll_loop(session)))
        return session

    async def stop(self, account_id: uuid.UUID, *, reason: str) -> None:
        async with self._lock:
            session = self._sessions.pop(str(account_id), None)
        if session is None or session._closed.is_set():
            return
        session._closed.set()

        for task in session._tasks:
            task.cancel()
        try:
            await session.relay.stop_screencast()
        except Exception as exc:  # session may already be gone
            log.debug(
                "remote_browser.stop_relay_failed", account_id=str(account_id), error=str(exc)
            )
        for closer in (session.context, session.browser):
            try:
                await closer.close()  # type: ignore[attr-defined]
            except Exception as exc:  # already closed/crashed is fine during cleanup
                log.debug(
                    "remote_browser.close_failed", account_id=str(account_id), error=str(exc)
                )

        await _release_slot(account_id, session.slot_token)
        log.info("remote_browser.session_closed", account_id=str(account_id), reason=reason)

    def get(self, account_id: uuid.UUID) -> RemoteBrowserSession | None:
        return self._sessions.get(str(account_id))

    # ── internals ────────────────────────────────────────────────────────────

    async def _launch(
        self, account_id: uuid.UUID, workspace_id: uuid.UUID, slot_token: str
    ) -> RemoteBrowserSession:
        async with AsyncSessionLocal() as db:
            account = (
                await db.execute(
                    select(LinkedInAccount).where(
                        LinkedInAccount.id == account_id,
                        LinkedInAccount.workspace_id == workspace_id,
                    )
                )
            ).scalar_one_or_none()
            if account is None:
                raise LaunchFailed("account not found")

            fp = dict(account.fingerprint or {})
            if "browser" not in fp:
                fp["browser"] = browser_fingerprint.generate(
                    timezone=account.timezone or "UTC"
                )
                account.fingerprint = fp
                await db.commit()

            resolved = proxy_mod.resolve(account.proxy)

        browser_fp = fp["browser"]
        viewport = browser_fingerprint.viewport(browser_fp)

        await xvfb.ensure_running()
        pw = await get_playwright()
        launch_kwargs: dict[str, object] = {
            "headless": False,
            "args": stealth.LAUNCH_ARGS,
        }
        if resolved is not None:
            launch_kwargs["proxy"] = to_playwright_proxy(resolved)

        browser = await pw.chromium.launch(**launch_kwargs)  # type: ignore[attr-defined]
        context = await browser.new_context(
            viewport=viewport,
            user_agent=browser_fingerprint.user_agent(browser_fp),
            locale=browser_fp.get("locale", "en-US"),
            timezone_id=browser_fp.get("timezone", "UTC"),
        )
        await context.add_init_script(stealth.INIT_SCRIPT)
        page = await context.new_page()
        cdp = await context.new_cdp_session(page)
        relay = CdpRelay(page, cdp)

        session = RemoteBrowserSession(
            account_id=account_id,
            workspace_id=workspace_id,
            browser=browser,
            context=context,
            page=page,
            relay=relay,
            slot_token=slot_token,
        )

        async def _on_frame(data: bytes) -> None:
            await session.push_frame(data)

        await relay.start_screencast(
            width=viewport["width"], height=viewport["height"], on_frame=_on_frame
        )
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        await session.push_status("live", "waiting for sign-in")
        return session

    async def _heartbeat_loop(self, session: RemoteBrowserSession) -> None:
        try:
            while not session._closed.is_set():
                await asyncio.sleep(_SLOT_HEARTBEAT_SECONDS)
                await _renew_slot(session.account_id, session.slot_token)
        except asyncio.CancelledError:
            pass

    async def _watchdog_loop(self, session: RemoteBrowserSession) -> None:
        try:
            while not session._closed.is_set():
                await asyncio.sleep(5)
                now = datetime.now(UTC)
                age = (now - session.created_at).total_seconds()
                idle = (now - session.last_input_at).total_seconds()
                if age >= settings.remote_browser_ttl_seconds:
                    await session.push_status("session_closed", "session time limit reached")
                    await self.stop(session.account_id, reason="ttl_expired")
                    return
                if idle >= settings.remote_browser_idle_timeout_seconds:
                    await session.push_status("session_closed", "no activity for a while")
                    await self.stop(session.account_id, reason="idle_timeout")
                    return
        except asyncio.CancelledError:
            pass

    async def _login_poll_loop(self, session: RemoteBrowserSession) -> None:
        try:
            while not session._closed.is_set():
                await asyncio.sleep(_LOGIN_POLL_SECONDS)
                if await self._check_logged_in(session):
                    await self._finish_login(session)
                    return
        except asyncio.CancelledError:
            pass

    async def _check_logged_in(self, session: RemoteBrowserSession) -> bool:
        cookies = await session.context.cookies()  # type: ignore[attr-defined]
        has_li_at = any(c["name"] == "li_at" and c["value"] for c in cookies)
        if not has_li_at:
            return False
        url = session.page.url  # type: ignore[attr-defined]
        return any(marker in url for marker in _AUTHENTICATED_URL_MARKERS)

    async def _finish_login(self, session: RemoteBrowserSession) -> None:
        cookies = await session.context.cookies()  # type: ignore[attr-defined]
        li_at = next((c["value"] for c in cookies if c["name"] == "li_at"), "")
        jsessionid = next((c["value"] for c in cookies if c["name"] == "JSESSIONID"), "")
        if not li_at:
            return

        linkedin_cookies = {
            c["name"]: c["value"] for c in cookies if "linkedin.com" in c.get("domain", "")
        }
        sealed = seal_for_transit(
            {"li_at": li_at, "jsessionid": jsessionid.strip('"'), "cookies": linkedin_cookies}
        )
        celery_app.send_task(
            "linkedin.auth.connect_cookie",
            args=[str(session.account_id), sealed],
            queue="linkedin.action",
        )
        await session.push_status("login_success", "signed in — finishing setup")
        log.info("remote_browser.login_success", account_id=str(session.account_id))
        # Grace period so the frontend can show the success state before the
        # browser closes out from under it.
        await asyncio.sleep(5)
        await self.stop(session.account_id, reason="login_success")


manager = RemoteBrowserManager()
