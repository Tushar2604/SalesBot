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
import queue
import threading
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

import redis.asyncio as aioredis
from redis.exceptions import RedisError
from sqlalchemy import select

from app.config import settings
from app.core import local_cache
from app.core.logging import get_logger
from app.db import AsyncSessionLocal
from app.linkedin import proxy as proxy_mod
from app.linkedin.remote_browser import browser_fingerprint, stealth, xvfb
from app.linkedin.remote_browser.cdp_relay import CdpRelay
from app.linkedin.remote_browser.playwright_pool import (
    get_playwright,
    run_on_playwright_loop,
    to_playwright_proxy,
)
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
_AUTHENTICATED_URL_MARKERS = (
    "linkedin.com/feed",
    "linkedin.com/mynetwork",
    "linkedin.com/in/",
    "linkedin.com/checkpoint",
    "linkedin.com/check/",
    "linkedin.com/notifications",
    "linkedin.com/jobs",
    "linkedin.com/messaging",
)


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
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )
    return client


async def _acquire_slot(account_id: uuid.UUID) -> str:
    token = str(uuid.uuid4())
    key = slot_key(account_id)
    client = _redis()
    try:
        if not await client.set(key, token, nx=True, ex=_SLOT_TTL_SECONDS):
            raise SlotBusy(f"account {account_id} is already acting")
        return token
    except (RedisError, OSError, ConnectionError):
        log.warning("remote_browser.slot_redis_unavailable", fallback="local_cache")
        if not local_cache.set_nx(key, token, _SLOT_TTL_SECONDS):
            raise SlotBusy(f"account {account_id} is already acting") from None
        return token
    finally:
        await client.aclose()


async def _renew_slot(account_id: uuid.UUID, token: str) -> None:
    key = slot_key(account_id)
    client = _redis()
    try:
        if await client.get(key) == token:
            await client.expire(key, _SLOT_TTL_SECONDS)
            return
    except (RedisError, OSError, ConnectionError):
        local_cache.expire(key, _SLOT_TTL_SECONDS)
        return
    finally:
        await client.aclose()


async def _release_slot(account_id: uuid.UUID, token: str) -> None:
    key = slot_key(account_id)
    client = _redis()
    try:
        if await client.get(key) == token:
            await client.delete(key)
            return
    except (RedisError, OSError, ConnectionError):
        local_cache.delete_if_value(key, token)
        return
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
    frame_queue: queue.Queue[bytes] = field(default_factory=lambda: queue.Queue(maxsize=2))
    status_queue: queue.Queue[StatusMessage] = field(default_factory=queue.Queue)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_input_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    _tasks: list[asyncio.Task[None]] = field(default_factory=list)
    _closed: threading.Event = field(default_factory=threading.Event)

    def touch(self) -> None:
        self.last_input_at = datetime.now(UTC)

    async def push_status(self, state: StatusState, detail: str = "") -> None:
        self.status_queue.put(StatusMessage(state=state, detail=detail))

    def push_frame(self, data: bytes) -> None:
        # Keep only the latest frame: a slow WS consumer should see the newest
        # screen state next, not catch up through a backlog of stale ones.
        try:
            self.frame_queue.put_nowait(data)
        except queue.Full:
            with contextlib.suppress(queue.Empty):
                self.frame_queue.get_nowait()
            with contextlib.suppress(queue.Full):
                self.frame_queue.put_nowait(data)

    async def next_frame(self) -> bytes:
        return await asyncio.to_thread(self.frame_queue.get)

    async def next_status(self) -> StatusMessage:
        return await asyncio.to_thread(self.status_queue.get)

    async def dispatch_input(self, message: MouseInput | KeyInput) -> None:
        self.touch()
        await run_on_playwright_loop(self.relay.dispatch_input(message))


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
            detail = str(exc).strip() or type(exc).__name__
            log.warning("remote_browser.launch_failed", account_id=str(account_id), error=detail)
            raise LaunchFailed(detail) from exc

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
            await run_on_playwright_loop(session.relay.stop_screencast())
        except Exception as exc:  # session may already be gone
            log.debug(
                "remote_browser.stop_relay_failed", account_id=str(account_id), error=str(exc)
            )
        for closer in (session.context, session.browser):
            try:
                await run_on_playwright_loop(closer.close())  # type: ignore[attr-defined]
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
        return await run_on_playwright_loop(
            self._open_chromium(
                account_id, workspace_id, slot_token, browser_fp, viewport, resolved
            )
        )

    async def _open_chromium(
        self,
        account_id: uuid.UUID,
        workspace_id: uuid.UUID,
        slot_token: str,
        browser_fp: dict,
        viewport: dict,
        resolved: object,
    ) -> RemoteBrowserSession:
        try:
            pw = await get_playwright()
        except ModuleNotFoundError as exc:
            raise LaunchFailed(
                "Playwright is not installed. Run: pip install '.[browser]' && playwright install chromium"
            ) from exc

        launch_kwargs: dict[str, object] = {
            "headless": False,
            "args": stealth.LAUNCH_ARGS,
        }
        if resolved is not None:
            launch_kwargs["proxy"] = to_playwright_proxy(resolved)

        try:
            browser = await pw.chromium.launch(**launch_kwargs)  # type: ignore[attr-defined]
        except Exception as headful_exc:
            log.warning("remote_browser.headful_failed", error=str(headful_exc))
            launch_kwargs["headless"] = True
            try:
                browser = await pw.chromium.launch(**launch_kwargs)  # type: ignore[attr-defined]
            except Exception as exc:
                raise LaunchFailed(
                    "Could not start Chromium. Run `playwright install chromium` in the API venv."
                ) from exc
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
            session.push_frame(data)

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
        async def _read() -> tuple[list, str]:
            cookies = await session.context.cookies()  # type: ignore[attr-defined]
            return cookies, session.page.url  # type: ignore[attr-defined]

        cookies, url = await run_on_playwright_loop(_read())
        has_li_at = any(c["name"] == "li_at" and c["value"] for c in cookies)
        if has_li_at:
            log.info("remote_browser.session_cookie_seen", url=url)
            return True
        return any(marker in url for marker in _AUTHENTICATED_URL_MARKERS)

    async def _finish_login(self, session: RemoteBrowserSession) -> None:
        async def _read_cookies() -> list:
            return await session.context.cookies()  # type: ignore[attr-defined]

        cookies = await run_on_playwright_loop(_read_cookies())
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
        from app.worker.tasks.linkedin_auth import connect_cookie

        if settings.environment == "development":
            await asyncio.to_thread(
                lambda: connect_cookie.apply(args=[str(session.account_id), sealed]).get()
            )
        else:
            try:
                celery_app.send_task(
                    "linkedin.auth.connect_cookie",
                    args=[str(session.account_id), sealed],
                    queue="linkedin.action",
                )
            except Exception as exc:
                log.warning("remote_browser.celery_unavailable", error=str(exc))
                await asyncio.to_thread(
                    lambda: connect_cookie.apply(args=[str(session.account_id), sealed]).get()
                )
        await session.push_status("login_success", "signed in — finishing setup")
        log.info("remote_browser.login_success", account_id=str(session.account_id))
        # Grace period so the frontend can show the success state before the
        # browser closes out from under it.
        await asyncio.sleep(5)
        await self.stop(session.account_id, reason="login_success")


manager = RemoteBrowserManager()
