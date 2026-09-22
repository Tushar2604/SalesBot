"""Lazy Playwright driver on a private event loop.

Uvicorn on Windows uses SelectorEventLoop, which cannot spawn subprocesses
(`asyncio.create_subprocess_exec` raises NotImplementedError). Playwright's
driver is a subprocess, so it must run on a ProactorEventLoop. One background
thread owns that loop; every Playwright await is marshaled onto it.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlsplit

from app.linkedin.proxy import ResolvedProxy

T = TypeVar("T")

_playwright: object | None = None
_pw_loop: asyncio.AbstractEventLoop | None = None
_pw_thread: threading.Thread | None = None
_pw_ready = threading.Event()
_pw_error: BaseException | None = None
_start_lock = threading.Lock()

_USER_BROWSERS = Path.home() / "AppData" / "Local" / "ms-playwright"


def _ensure_browsers_path() -> None:
    """Prefer a real user cache if Cursor's temp Playwright path is empty."""
    current = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
    if current and any(Path(current).glob("chromium-*")):
        return
    if any(_USER_BROWSERS.glob("chromium-*")):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_USER_BROWSERS)


def _thread_main() -> None:
    global _playwright, _pw_loop, _pw_error
    _ensure_browsers_path()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _pw_loop = loop
    try:
        from playwright.async_api import async_playwright

        _playwright = loop.run_until_complete(async_playwright().start())
        _pw_ready.set()
        loop.run_forever()
    except BaseException as exc:
        _pw_error = exc
        _pw_ready.set()
        raise


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _pw_thread, _pw_error
    with _start_lock:
        if _pw_thread is None or not _pw_thread.is_alive():
            _pw_ready.clear()
            _pw_error = None
            _pw_thread = threading.Thread(target=_thread_main, name="playwright-loop", daemon=True)
            _pw_thread.start()
    if not _pw_ready.wait(timeout=60):
        raise RuntimeError("Playwright driver timed out while starting")
    if _pw_error is not None:
        raise RuntimeError(f"Playwright driver failed: {_pw_error}") from _pw_error
    if _pw_loop is None or _playwright is None:
        raise RuntimeError("Playwright driver failed to start")
    return _pw_loop


async def run_on_playwright_loop(coro: Coroutine[Any, Any, T]) -> T:
    """Await `coro` on the Playwright loop, from any asyncio loop."""
    loop = _ensure_loop()
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:
        return await coro
    return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(coro, loop))


async def get_playwright() -> object:
    """Returns the shared Playwright instance. Safe to call from any loop."""
    _ensure_loop()
    if _playwright is None:
        raise RuntimeError("Playwright driver failed to start")
    return _playwright


def to_playwright_proxy(resolved: ResolvedProxy) -> dict[str, str]:
    """Adapts `proxy.resolve()`'s httpx-style URL into Playwright's proxy dict shape.

    `resolved.url` already has the sticky-session suffix baked into the
    username (see `proxy.py`) and is percent-encoded; `urlsplit`'s
    `.username`/`.password` properties decode it back, so there is no need to
    re-derive the sticky-session logic here.
    """
    parts = urlsplit(resolved.url)
    proxy: dict[str, str] = {"server": f"{parts.scheme}://{parts.hostname}:{parts.port}"}
    if parts.username:
        proxy["username"] = parts.username
    if parts.password:
        proxy["password"] = parts.password
    return proxy
