"""Lazy, process-wide Playwright driver, and the proxy shape adapter.

Playwright's own driver process is heavy to start; it is started once, lazily,
on the first remote-browser session rather than at import time or container
boot — most of the time nobody is connecting an account, and there is no
reason to pay Chromium's/Playwright's baseline memory cost until someone does.
"""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit

from app.linkedin.proxy import ResolvedProxy

_playwright: object | None = None
_playwright_lock = asyncio.Lock()


async def get_playwright() -> object:
    """Returns the shared `async_playwright()` context object, starting it on first use."""
    global _playwright
    async with _playwright_lock:
        if _playwright is None:
            # Imported lazily: this module (and its native driver binary) is
            # only present when the `browser` optional dependency group is
            # installed, which only the `api` image does.
            from playwright.async_api import async_playwright

            _playwright = await async_playwright().start()
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
