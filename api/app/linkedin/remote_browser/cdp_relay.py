"""Screencast frames out, input events in — both over one CDP session.

`Page.startScreencast` pushes JPEG frames as the real page repaints; each must
be acknowledged before Chrome sends the next one. Input goes the other way:
`Input.dispatchMouseEvent`/`Input.dispatchKeyEvent` make the real page believe
a real pointer/keyboard is driving it, because for this flow one genuinely is
— a human, relayed through here.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.linkedin.remote_browser.protocol import KeyInput, MouseInput, TextInput

if TYPE_CHECKING:
    from playwright.async_api import CDPSession, Page

log = get_logger(__name__)

_MOUSE_EVENT_TYPE = {
    "mousedown": "mousePressed",
    "mouseup": "mouseReleased",
    "mousemove": "mouseMoved",
    "wheel": "mouseWheel",
}
_KEY_EVENT_TYPE = {"keydown": "keyDown", "keyup": "keyUp"}


class CdpRelay:
    """One instance per live remote-browser session."""

    def __init__(self, page: Page, cdp: CDPSession) -> None:
        self._page = page
        self._cdp = cdp
        self._on_frame: Callable[[bytes], Awaitable[None]] | None = None
        self._loop = asyncio.get_event_loop()

    async def start_screencast(
        self, *, width: int, height: int, on_frame: Callable[[bytes], Awaitable[None]]
    ) -> None:
        self._on_frame = on_frame
        self._cdp.on("Page.screencastFrame", self._handle_frame)
        await self._cdp.send(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": 65,
                "maxWidth": width,
                "maxHeight": height,
                "everyNthFrame": 1,
            },
        )

    async def stop_screencast(self) -> None:
        self._on_frame = None
        try:
            await self._cdp.send("Page.stopScreencast")
        except Exception as exc:  # the page/session may already be gone
            log.debug("remote_browser.stop_screencast_failed", error=str(exc))

    def _handle_frame(self, event: dict[str, Any]) -> None:
        # CDPSession event handlers are plain callbacks, not coroutines — hand
        # the ack + user callback off to the event loop rather than blocking
        # whatever dispatched this event.
        self._loop.create_task(self._process_frame(event))

    async def _process_frame(self, event: dict[str, Any]) -> None:
        import base64

        session_id = event.get("sessionId")
        try:
            if self._on_frame is not None:
                data = base64.b64decode(event["data"])
                await self._on_frame(data)
        finally:
            if session_id is not None:
                try:
                    await self._cdp.send("Page.screencastFrameAck", {"sessionId": session_id})
                except Exception as exc:
                    log.debug("remote_browser.frame_ack_failed", error=str(exc))

    async def dispatch_input(self, message: MouseInput | KeyInput | TextInput) -> None:
        try:
            if isinstance(message, TextInput):
                await self._cdp.send("Input.insertText", {"text": message.text})
            elif isinstance(message, MouseInput):
                await self._cdp.send(
                    "Input.dispatchMouseEvent",
                    {
                        "type": _MOUSE_EVENT_TYPE[message.event],
                        "x": message.x,
                        "y": message.y,
                        # Blink only fires `click` when the release also has
                        # clickCount >= 1; a moved pointer carries no button.
                        "button": (
                            message.button
                            if message.event in ("mousedown", "mouseup")
                            else "none"
                        ),
                        "clickCount": 1 if message.event in ("mousedown", "mouseup") else 0,
                        "deltaX": 0,
                        "deltaY": message.delta_y,
                    },
                )
            else:
                # keyDown carrying `text` already inserts the character; a
                # following insertText would type it twice. Keys without text
                # (Backspace, Tab, arrows) must be rawKeyDown to act as edits.
                event_type = _KEY_EVENT_TYPE[message.event]
                if event_type == "keyDown" and not message.text:
                    event_type = "rawKeyDown"
                payload: dict[str, object] = {
                    "type": event_type,
                    "key": message.key,
                    "code": message.code,
                    "windowsVirtualKeyCode": message.windows_virtual_key_code,
                    "nativeVirtualKeyCode": message.windows_virtual_key_code,
                    "modifiers": message.modifiers,
                }
                if message.text:
                    payload["text"] = message.text
                    payload["unmodifiedText"] = message.text
                await self._cdp.send("Input.dispatchKeyEvent", payload)
        except Exception as exc:
            log.warning("remote_browser.input_dispatch_failed", error=str(exc))
