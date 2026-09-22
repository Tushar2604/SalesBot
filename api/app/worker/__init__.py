"""Celery worker package.

`app.worker.celery_app` is the entry point for both containers
(`celery -A app.worker.celery_app worker|beat`). Task modules are registered
through that module's `include` list, not by importing them here — keeping this
file empty of side effects avoids a circular import with `celery_app`.
"""
