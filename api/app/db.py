"""Database engines and session factories.

Two stacks intentionally coexist:

* **async** (`asyncpg`) — used by FastAPI request handlers.
* **sync** (`psycopg`) — used by Celery tasks and Alembic. Celery tasks are
  ordinary blocking functions; running an event loop inside each one buys
  nothing and complicates the per-account locking.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

# ── async (API) ───────────────────────────────────────────────────────────────
async_engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Commits on success, rolls back on exception."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ── sync (Celery, Alembic) ────────────────────────────────────────────────────
sync_engine = create_engine(
    settings.sync_database_url,
    echo=settings.db_echo,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_pre_ping=True,
)

SyncSessionLocal = sessionmaker(sync_engine, expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope for worker code: `with session_scope() as db: ...`"""
    session = SyncSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
