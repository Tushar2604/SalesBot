"""Celery application.

Queue layout mirrors the plan's isolation requirement: a slow or backed-up queue
must never delay the critical path.

  linkedin.action  — outbound LinkedIn actions. One in-flight action per account
                     is enforced by a Redis slot lock inside the task, not by
                     worker concurrency, so the pool can be sized freely.
  linkedin.sync    — conversation polling, invite-acceptance checks, withdrawals.
  email.send       — SMTP/OAuth sends and warmup.
  ai               — Claude generation and classification.
  content.publish  — Content Studio post publishing. Isolated from
                     `linkedin.action` on purpose: publishing goes through the
                     official API with a member OAuth grant and shares none of
                     the automation queue's pacing or slot constraints, so a
                     backed-up outreach queue must never delay a scheduled post.
  webhooks         — outbound delivery with retry + DLQ.

`acks_late` plus `reject_on_worker_lost` means a killed worker's task is
redelivered; duplicate side effects are prevented by the unique idempotency key
on `action_tasks`, never by hoping a task runs once.
"""

from __future__ import annotations

from celery import Celery
from celery.signals import setup_logging

from app.config import settings
from app.core.logging import configure_logging

celery_app = Celery(
    "salesrobo",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    # Task modules are listed explicitly: the worker is started with
    # `-A app.worker.celery_app`, which imports only this module, so anything
    # not listed here would be an unregistered-task error at dispatch time.
    include=[
        "app.worker.tasks.scheduler",
        "app.worker.tasks.linkedin_auth",
        "app.worker.tasks.actions",
        "app.worker.tasks.sync",
        "app.worker.tasks.ai",
        "app.worker.tasks.assistant",
        "app.worker.tasks.content",
    ],
)

celery_app.conf.update(
    task_default_queue="default",
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=600,
    task_soft_time_limit=540,
    broker_transport_options={"visibility_timeout": 3600},
    result_expires=86400,
    task_routes={
        "linkedin.auth.*": {"queue": "linkedin.action"},
        "linkedin.action.*": {"queue": "linkedin.action"},
        "linkedin.sync.*": {"queue": "linkedin.sync"},
        "content.*": {"queue": "content.publish"},
        "email.*": {"queue": "email.send"},
        "ai.*": {"queue": "ai"},
        "assistant.*": {"queue": "ai"},
        "webhooks.*": {"queue": "webhooks"},
        "scheduler.*": {"queue": "default"},
    },
)

# Beat schedule. The dispatcher tick is the heartbeat of the safety engine; the
# remaining entries are hygiene jobs that keep accounts healthy.
celery_app.conf.beat_schedule = {
    # Probe stored sessions so an expired one is found before a campaign uses it.
    "verify-linkedin-sessions": {
        "task": "linkedin.sync.verify_all",
        # Every check is a real browser page load; a session probe every half
        # hour, all night, is itself the kind of pattern worth not creating.
        "schedule": 21600.0,
        "options": {"expires": 3600},
    },
    # Replies and acceptances: the inbound state the sequence engine reads.
    "poll-linkedin-inbound": {
        "task": "linkedin.sync.poll_all",
        "schedule": 600.0,
        "options": {"expires": 540},
    },
    # Claims scheduled posts whose slot has arrived. A scheduled post is a row,
    # not a delayed job, so this sweep is what makes rescheduling and cancelling
    # ordinary UPDATEs with no orphaned job to chase.
    "content-sweep-due": {
        "task": "content.sweep_due",
        "schedule": 60.0,
        "options": {"expires": 55},
    },
    "dispatcher-tick": {
        "task": "scheduler.tick",
        "schedule": 60.0,
        "options": {"expires": 55},
    },
}


@setup_logging.connect
def _configure_celery_logging(**_kwargs: object) -> None:
    configure_logging()


@celery_app.task(name="ops.ping")
def ping() -> str:
    """Liveness check for the worker pool."""
    return "pong"
