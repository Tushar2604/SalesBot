"""Inbound-message classification.

One label out of `ConversationLabel` per inbound message, via a forced
tool-call so the model can only return one of the set values — no free-text
parsing to get wrong. A classification failure (missing key, API error,
malformed response) must never block message ingestion, so every failure
mode here falls back to `OTHER` rather than raising.
"""

from __future__ import annotations

from typing import Any

import anthropic

from app.config import settings
from app.core.logging import get_logger
from app.models.inbox import ConversationLabel

log = get_logger(__name__)

_LABELS = [label.value for label in ConversationLabel if label is not ConversationLabel.NONE]

_SYSTEM_PROMPT = (
    "You classify a single inbound LinkedIn message received during B2B sales "
    "outreach. Pick the one label that best describes the sender's intent, and "
    "record it by calling the classify tool exactly once."
)

_TOOL: dict[str, Any] = {
    "name": "classify",
    "description": "Record the classification for the inbound message.",
    "input_schema": {
        "type": "object",
        "properties": {
            "label": {
                "type": "string",
                "enum": _LABELS,
                "description": "The single best-fitting label for the message.",
            },
        },
        "required": ["label"],
    },
}

_MAX_INPUT_CHARS = 4000

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic | None:
    """Lazily builds the SDK client; `None` when no key is configured."""
    global _client
    api_key = settings.anthropic_api_key.get_secret_value()
    if not api_key:
        return None
    if _client is None:
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def classify_inbound(text: str) -> ConversationLabel:
    """Best-effort label for one inbound message body. Never raises."""
    client = _get_client()
    if client is None or not text.strip():
        return ConversationLabel.OTHER

    try:
        response = client.messages.create(
            model=settings.ai_classification_model,
            max_tokens=64,
            system=_SYSTEM_PROMPT,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "classify"},
            messages=[{"role": "user", "content": text[:_MAX_INPUT_CHARS]}],
        )
        for block in response.content:
            if block.type == "tool_use" and block.name == "classify":
                label = str(block.input.get("label", "")).strip()
                if label in _LABELS:
                    return ConversationLabel(label)
        return ConversationLabel.OTHER
    except Exception:
        log.warning("ai.classify_failed", exc_info=True)
        return ConversationLabel.OTHER
