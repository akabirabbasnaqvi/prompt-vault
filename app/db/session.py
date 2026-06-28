"""
app/db/session.py

Async database engine and session factory.

SKILLS DEMONSTRATED:
  - SQLAlchemy 2.0 async engine
  - Connection pooling
  - FastAPI dependency injection pattern
  - Python async/await
  - Context managers

This file is the bridge between FastAPI and PostgreSQL.
"""

from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    create_async_engine,
    async_sessionmaker,
)
from app.core.config import settings


# ─────────────────────────────────────────────────────────────────────
# ASYNC ENGINE
#
# The engine is the core connection interface to PostgreSQL.
# It manages the connection pool — a set of real TCP connections
# that stay open and ready to use.
#
# create_async_engine → creates an engine that uses asyncio
#   pool_size       → always keep this many connections open
#   max_overflow    → allow this many EXTRA connections when pool is full
#   pool_timeout    → raise an error if we wait this long for a connection
#   pool_pre_ping   → before using a connection, send a quick "are you alive?"
#                     ping to PostgreSQL. If the connection dropped (e.g. after
#                     a server restart), it gets discarded and a new one is made.
#                     This prevents "connection is closed" errors in production.
#   echo            → in DEBUG mode, print every SQL query to the terminal.
#                     Extremely useful for learning and debugging.
#                     NEVER enable this in production.
# ─────────────────────────────────────────────────────────────────────
engine: AsyncEngine = create_async_engine(
    url=settings.database_url,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
    pool_timeout=settings.db_pool_timeout,
    pool_pre_ping=True,
    echo=settings.debug,       # Print SQL queries in development
)


# ─────────────────────────────────────────────────────────────────────
# SESSION FACTORY
#
# A session is your "unit of work" with the database.
# You open a session, do your reads/writes, then close it.
# Each request in FastAPI gets its own session.
#
# async_sessionmaker creates a factory that produces AsyncSession objects.
#
#   expire_on_commit=False → After committing, keep the data in memory.
#                            Without this, accessing object attributes after
#                            commit would trigger another database query.
#                            For async code, this causes errors.
#                            Always set this to False in async SQLAlchemy.
# ─────────────────────────────────────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,   # We manually control transactions (best practice)
    autoflush=False,    # We manually flush (more predictable behavior)
)


# ─────────────────────────────────────────────────────────────────────
# DATABASE SESSION DEPENDENCY
#
# SKILL: FastAPI Dependency Injection
#
# This is a "dependency" — a function FastAPI calls automatically
# before running any route that requests it.
#
# How it works:
#   1. FastAPI sees a route that has `db: AsyncSession = Depends(get_db)`
#   2. Before calling the route function, FastAPI calls get_db()
#   3. get_db() opens a database session
#   4. Yields the session to the route function (route runs here)
#   5. After the route finishes (even if it crashed), the code after
#      yield runs: the session is closed and returned to the pool
#
# The "yield" makes this a context manager dependency.
# "try/finally" guarantees the session is ALWAYS closed,
# even if the route raised an exception. This prevents connection leaks.
#
# WHY DEPENDENCY INJECTION:
#   - Every route gets a fresh, clean session
#   - Sessions are automatically cleaned up
#   - In tests, we can replace get_db() with a test database session
#     without changing a single line of production code
#   - Routes do not need to know HOW to create sessions, just that they
#     will receive one
# ─────────────────────────────────────────────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides an async database session.

    Usage in a route:
        @app.get("/prompts")
        async def list_prompts(db: AsyncSession = Depends(get_db)):
            result = await db.execute(select(Prompt))
            return result.scalars().all()

    The session is automatically opened before the route runs
    and closed after it finishes, whether it succeeded or failed.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            # If we get here without an exception, commit any pending changes
            await session.commit()
        except Exception:
            # If anything went wrong, roll back ALL changes from this request.
            # This is transactional safety — either everything succeeds or
            # nothing is saved. No partial writes.
            await session.rollback()
            raise
        finally:
            # This ALWAYS runs. Close the session and return the
            # underlying connection back to the pool.
            await session.close()