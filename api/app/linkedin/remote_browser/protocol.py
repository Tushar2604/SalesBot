"""Wire protocol for the remote-browser WebSocket.

Screencast frames themselves go over the socket as raw JPEG bytes
(`websocket.send_bytes`) — no envelope, since the client only ever does one
thing with them (draw the latest one to a canvas) and a JSON+base64 wrapper
would just add overhead to something already sent many times a second.
Everything else — status updates server→client, input events client→server —
is JSON, modeled here so both directions have one place that defines the
shape.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field, TypeAdapter

# ── server → client ──────────────────────────────────────────────────────────

StatusState = Literal["launching", "live", "login_success", "session_closed", "error"]


class StatusMessage(BaseModel):
    type: Literal["status"] = "status"
    state: StatusState
    detail: str = ""


# ── client → server ──────────────────────────────────────────────────────────


class MouseInput(BaseModel):
    type: Literal["mouse"] = "mouse"
    event: Literal["mousedown", "mouseup", "mousemove", "wheel"]
    x: float
    y: float
    button: Literal["left", "middle", "right"] = "left"
    delta_y: float = 0.0


class KeyInput(BaseModel):
    type: Literal["key"] = "key"
    event: Literal["keydown", "keyup"]
    key: str
    code: str
    windows_virtual_key_code: int = 0
    text: str = ""
    # CDP bitmask: Alt=1, Ctrl=2, Meta=4, Shift=8.
    modifiers: int = 0


class TextInput(BaseModel):
    """A pasted string, inserted as-is at the focused element."""

    type: Literal["text"] = "text"
    text: str = Field(max_length=2000)


InputMessage = Annotated[MouseInput | KeyInput | TextInput, Field(discriminator="type")]

# `input_message_adapter.validate_json(raw)` parses one incoming client
# message and dispatches to `MouseInput`/`KeyInput`/`TextInput` by its `type` field.
input_message_adapter: TypeAdapter[MouseInput | KeyInput | TextInput] = TypeAdapter(InputMessage)
