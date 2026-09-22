"""Lazily starts one shared Xvfb virtual display for headful Chromium.

Started on first use, not at container boot: most of the time nobody is
running a remote-browser session, and there is no reason to keep an X server
(and the baseline memory that comes with it) resident until someone does.
Real headful Chromium under Xvfb is used deliberately instead of Chromium's
own headless mode — see stealth.py's docstring for why.

`DISPLAY` itself is baked into the image (Dockerfile `ENV DISPLAY=:99`), not
set here via `os.environ` at runtime: Playwright's browser process is spawned
by a separate Node.js driver subprocess, and a live env mutation in this
Python process isn't reliably visible to a process that driver spawns later.
This module's only job is making sure something is actually listening on
that fixed display before Chromium tries to use it.
"""

from __future__ import annotations

import asyncio
import shutil
from typing import Final

from app.core.logging import get_logger

log = get_logger(__name__)

DISPLAY: Final[str] = ":99"

_process: asyncio.subprocess.Process | None = None
_lock = asyncio.Lock()


async def ensure_running() -> str:
    """Returns the DISPLAY value to use, starting the X server if needed."""
    global _process
    async with _lock:
        if _process is not None and _process.returncode is None:
            return DISPLAY

        xvfb_path = shutil.which("Xvfb")
        if xvfb_path is None:
            raise RuntimeError(
                "Xvfb is not installed in this image — the api container must be "
                "built from the browser-enabled Dockerfile target for remote-browser "
                "login to work"
            )

        _process = await asyncio.create_subprocess_exec(
            xvfb_path,
            DISPLAY,
            "-screen",
            "0",
            "1920x1080x24",
            "-nolisten",
            "tcp",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.sleep(0.5)  # give the X server a moment to bind before use
        log.info("remote_browser.xvfb_started", display=DISPLAY, pid=_process.pid)

    return DISPLAY
