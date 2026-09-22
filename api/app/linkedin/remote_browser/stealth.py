"""Launch flags and page patches that keep a real Chromium session from
announcing itself as automated.

Deliberately minimal — a short, documented list of the specific tells known to
matter here, not an attempt at a general stealth-plugin reimplementation.
That's an arms race outside this module's job, which is only to make a
*human-driven* login session look like an ordinary browser, not to disguise
ongoing automation (Phase 1 never sends automated actions through this
browser — see the module docstring in `manager.py`).
"""

from __future__ import annotations

from typing import Final

LAUNCH_ARGS: Final[list[str]] = [
    "--disable-blink-features=AutomationControlled",
    # Containers commonly have no working user namespace for Chromium's
    # sandbox; the container itself is the isolation boundary here.
    "--no-sandbox",
    # /dev/shm is tiny by default in Docker and Chromium's shared-memory use
    # crashes tabs under it rather than gracefully falling back.
    "--disable-dev-shm-usage",
]

# Patches applied via `page.add_init_script` before any LinkedIn script runs,
# undoing the handful of automation tells Playwright's own defaults leave
# behind even with AutomationControlled disabled.
INIT_SCRIPT: Final[str] = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
window.chrome = window.chrome || { runtime: {} };
"""
