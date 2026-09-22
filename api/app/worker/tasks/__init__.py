"""Celery task modules. Importing a module here registers its tasks."""

from app.worker.tasks import content, scheduler

__all__ = ["content", "scheduler"]
