"""Test fixtures.

Tests run against a real Postgres (`salesrobo_test`, created on demand) rather
than SQLite: the schema uses JSONB, native enums, and RLS, none of which SQLite
models faithfully. Each test gets a clean transaction that is rolled back, so
tests are order-independent without paying for a schema rebuild per test.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db import get_db
from app.main import create_app
from app.models import Base

TEST_DB_NAME = "salesrobo_test"
_base_url, _ = settings.database_url.rsplit("/", 1)
TEST_DATABASE_URL = f"{_base_url}/{TEST_DB_NAME}"
ADMIN_DATABASE_URL = f"{_base_url}/postgres"


async def _ensure_test_database() -> None:
    admin = create_async_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": TEST_DB_NAME}
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    finally:
        await admin.dispose()


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[object]:
    await _ensure_test_database()
    eng = create_async_engine(TEST_DATABASE_URL, poolclass=None)
    async with eng.begin() as conn:
        # Drop the schema rather than `drop_all`: that resolves FK cycles and
        # also clears native enum types, which `drop_all` leaves behind and
        # which then collide on the next create.
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def db(engine) -> AsyncIterator[AsyncSession]:  # type: ignore[no-untyped-def]
    """Session bound to an outer transaction that is always rolled back."""
    connection = await engine.connect()
    transaction = await connection.begin()

    # `create_savepoint` makes service code's own commit() land on a SAVEPOINT
    # instead of ending the outer transaction, so the rollback below still wins
    # and every test starts from an empty schema.
    session_factory = async_sessionmaker(
        bind=connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    session = session_factory()

    try:
        yield session
    finally:
        await session.close()
        if transaction.is_active:
            await transaction.rollback()
        await connection.close()


@pytest.fixture
async def client(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db
        # Production's `get_db` commits when the handler returns. Without an
        # equivalent flush here, writes stay pending in the session and a
        # follow-up request in the same test cannot see them. On an exception
        # the generator is not resumed, which mirrors the rollback path.
        await db.flush()

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test", follow_redirects=True
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
def signup_payload() -> dict[str, str]:
    return {
        "email": "founder@example.com",
        "password": "correct horse 7",
        "full_name": "Test Founder",
        "workspace_name": "Acme Outbound",
    }


# ── synchronous session, for the scheduler and worker code ───────────────────
# The dispatcher, engine, and quota accounting are deliberately synchronous
# (they run in Celery workers), so they need a sync session bound to the same
# test database the async fixtures built.


@pytest.fixture(scope="session")
def sync_engine(engine):  # type: ignore[no-untyped-def]
    from sqlalchemy import create_engine

    _ = engine  # ensures the schema exists before this engine is used
    eng = create_engine(TEST_DATABASE_URL.replace("+asyncpg", "+psycopg"))
    yield eng
    eng.dispose()


@pytest.fixture
def sdb(sync_engine):  # type: ignore[no-untyped-def]
    """Sync session in a transaction that is always rolled back."""
    from sqlalchemy.orm import sessionmaker

    connection = sync_engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection,
        expire_on_commit=False,
        autoflush=False,
        join_transaction_mode="create_savepoint",
    )
    session = factory()
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()
