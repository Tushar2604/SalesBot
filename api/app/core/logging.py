"""Structured logging with mandatory secret redaction.

Secrets in this system are long-lived LinkedIn sessions and proxy credentials.
A single leaked log line is an account takeover, so redaction is a processor in
the logging pipeline rather than a convention developers must remember.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

import structlog

from app.config import settings

_REDACT_KEYS = {
    "password",
    "password_hash",
    "token",
    "access_token",
    "refresh_token",
    "jwt",
    "authorization",
    "cookie",
    "cookies",
    "li_at",
    "li_a",
    "jsessionid",
    "csrf_token",
    "session_ciphertext",
    "encryption_key",
    "secret",
    "api_key",
    "anthropic_api_key",
    "stripe_secret_key",
    "proxy_password",
    "creds_ciphertext",
}

# Catches secrets embedded in free-text messages (e.g. an upstream error body).
_COOKIE_PATTERN = re.compile(r"(li_at|li_a|JSESSIONID)=\"?[^;\s\"']+\"?", re.IGNORECASE)
_BEARER_PATTERN = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: ("«redacted»" if k.lower() in _REDACT_KEYS else _redact(v)) for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(_redact(v) for v in value)
    if isinstance(value, str):
        value = _COOKIE_PATTERN.sub(r"\1=«redacted»", value)
        value = _BEARER_PATTERN.sub(r"\1«redacted»", value)
        return value
    return value


def redaction_processor(
    _logger: Any, _name: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    redacted: structlog.types.EventDict = _redact(dict(event_dict))
    return redacted


def configure_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))
    # `celery.app.trace` is deliberately NOT muted: its received/succeeded/failed
    # lines are the only per-action audit trail in the worker logs, and losing
    # them makes a stuck account impossible to diagnose from logs alone.

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if settings.is_production
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            redaction_processor,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
