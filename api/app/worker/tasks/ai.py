"""AI classification of inbound messages.

Dispatched once per new inbound message from `sync.py::poll_replies`, never
called inline there — an Anthropic call must not compete with the account's
lock window or slow down reply-stop detection.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.ai.classify import classify_inbound
from app.core.logging import get_logger
from app.db import session_scope
from app.integrations import events as integration_events
from app.models.inbox import Conversation, LabelSource, Message, MessageDirection
from app.models.leads import Lead
from app.worker.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="ai.classify_message", bind=True, max_retries=2)
def classify_message(self: Any, message_id: str) -> dict[str, int]:
    _ = self
    with session_scope() as db:
        message = db.get(Message, message_id)
        if message is None or message.direction is not MessageDirection.INBOUND:
            return {"classified": 0}

        label = classify_inbound(message.body)
        message.ai_label = label
        message.ai_classified_at = datetime.now(UTC)

        conversation = db.get(Conversation, message.conversation_id)
        # A human's own label wins; AI only fills in an unset/AI-set one.
        if conversation is not None and conversation.label_source is not LabelSource.MANUAL:
            changed = conversation.label != label
            conversation.label = label
            conversation.label_source = LabelSource.AI
            if changed:
                lead = db.get(Lead, conversation.lead_id) if conversation.lead_id else None
                integration_events.emit_sync(
                    db,
                    conversation.workspace_id,
                    "conversation.labeled",
                    {
                        "conversation_id": str(conversation.id),
                        "label": label.value,
                        "message_text": message.body,
                        "lead": integration_events.lead_data(lead),
                    },
                )

        log.info("ai.message_classified", message_id=str(message.id), label=label.value)
    return {"classified": 1}
