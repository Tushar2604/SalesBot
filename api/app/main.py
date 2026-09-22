"""FastAPI application factory.

This process never talks to LinkedIn. It authenticates, validates, persists
intent, and enqueues work; the Celery workers own every outbound action. Keeping
that boundary strict is what lets the API scale to N stateless replicas while
each LinkedIn account keeps exactly one execution slot.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.router import api_router
from app.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger
from app.db import async_engine

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    log.info("api.starting", environment=settings.environment)
    yield
    await async_engine.dispose()
    log.info("api.stopped")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Salesrobo API",
        version="0.1.0",
        description="Multi-tenant LinkedIn + email outreach automation.",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,  # required for the httpOnly refresh cookie
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router)

    @app.get("/health", tags=["ops"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["ops"])
    async def ready() -> dict[str, str]:
        """Readiness probe: fails the pod out of rotation if Postgres is unreachable."""
        async with async_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ready"}

    return app


app = create_app()
