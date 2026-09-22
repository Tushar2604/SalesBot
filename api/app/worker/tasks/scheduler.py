"""The dispatcher tick — the heartbeat of the safety engine.

Runs every 60 seconds. It materialises due enrollments into `ActionTask` rows
and then dispatches at most one task per eligible account, after walking every
gate. All of the reasoning lives in `app.scheduler.dispatcher`; this module is
only the Celery entry point, so the engine stays testable without a broker.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.db import session_scope
from app.scheduler import dispatcher
from app.worker.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="scheduler.tick")
def tick() -> dict[str, object]:
    with session_scope() as db:
        return dispatcher.tick(db).as_dict()
