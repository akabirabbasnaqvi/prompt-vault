"""
tests/conftest.py
Rewritten to fix asyncpg connection conflicts with pytest-asyncio 0.23.x
"""

import pytest
import pytest_asyncio
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport
import fakeredis.aioredis
import psycopg2

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    create_async_engine,
    AsyncSession,
    async_sessionmaker,
)

from app.main import app
from app.db.base import Base
from app.db.session import get_db
from app.core.cache import get_redis
from app.core.config import settings

# ─────────────────────────────────────────────────────────────────────
# Build test database URL safely
# rsplit from right so only the DB name is replaced, not the username
# ─────────────────────────────────────────────────────────────────────
TEST_DATABASE_URL = (
    settings.database_url.rsplit("/promptvault", 1)[0] + "/promptvault_test"
)

# ─────────────────────────────────────────────────────────────────────
# SYNC SETUP — use psycopg2 to create/drop tables ONCE
# This avoids all async event loop scope conflicts entirely.
# We call this from a regular (non-async) session-scoped fixture.
# ─────────────────────────────────────────────────────────────────────
SYNC_TEST_DB_URL = TEST_DATABASE_URL.replace(
    "postgresql+asyncpg://", "postgresql://"
)


def _sync_create_tables():
    """Create all tables synchronously using psycopg2."""
    conn = psycopg2.connect(SYNC_TEST_DB_URL)
    conn.autocommit = True
    cur = conn.cursor()
    # Drop and recreate all tables via SQLAlchemy sync engine
    from sqlalchemy import create_engine
    sync_engine = create_engine(SYNC_TEST_DB_URL)
    Base.metadata.drop_all(sync_engine)
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    cur.close()
    conn.close()


# ─────────────────────────────────────────────────────────────────────
# SESSION FIXTURE — sync, runs once per test session
# ─────────────────────────────────────────────────────────────────────
@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Create tables once before all tests. Drop after all tests."""
    _sync_create_tables()
    yield
    # Teardown: drop all tables after all tests complete
    from sqlalchemy import create_engine
    sync_engine = create_engine(SYNC_TEST_DB_URL)
    Base.metadata.drop_all(sync_engine)
    sync_engine.dispose()


# ─────────────────────────────────────────────────────────────────────
# ASYNC DB SESSION — wrap each test in a transaction that rolls back
# ─────────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture(scope="session")
async def async_engine():
    """Shared async engine for the whole test session."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
    )
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(async_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provides an isolated async DB session per test.

    The outer transaction is rolled back after each test, so data changes
    never leak between tests and we avoid expensive table truncation.
    """
    connection = await async_engine.connect()
    transaction = await connection.begin()
    session_factory = async_sessionmaker(
        bind=connection,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )
    session = session_factory()

    @event.listens_for(session.sync_session, "after_transaction_end")
    def restart_nested_transaction(session_obj, transaction_obj):
        if transaction_obj.nested and not transaction_obj._parent.nested:
            session_obj.begin_nested()

    await session.begin_nested()

    try:
        yield session
    finally:
        await session.close()
        await transaction.rollback()
        await connection.close()


# ─────────────────────────────────────────────────────────────────────
# FAKE REDIS
# ─────────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def fake_redis():
    """In-memory Redis — no real Redis server needed."""
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield redis
    redis.close()    # ← remove await, change aclose() to close()


# ─────────────────────────────────────────────────────────────────────
# HTTP CLIENT with dependency overrides
# ─────────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def client(db_session: AsyncSession, fake_redis) -> AsyncGenerator[AsyncClient, None]:
    """Async HTTP client with test DB and fake Redis injected."""

    async def override_get_db():
        yield db_session

    async def override_get_redis():
        yield fake_redis

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_redis] = override_get_redis

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


# ─────────────────────────────────────────────────────────────────────
# DATA FIXTURES
# ─────────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def sample_workspace(client: AsyncClient) -> dict:
    """Creates a workspace and returns response data."""
    response = await client.post(
        "/api/v1/workspaces/",
        json={
            "name": "Test Workspace",
            "slug": "test-workspace",
            "description": "A workspace for testing",
        },
    )
    assert response.status_code == 201
    return response.json()


@pytest_asyncio.fixture
async def sample_prompt(client: AsyncClient, sample_workspace: dict) -> dict:
    """Creates a prompt inside test-workspace."""
    response = await client.post(
        "/api/v1/workspaces/test-workspace/prompts/",
        json={
            "name": "Test Prompt",
            "slug": "test-prompt",
            "description": "A prompt for testing",
            "tags": "test,evaluation",
        },
    )
    assert response.status_code == 201
    return response.json()