"""
alembic/env.py

Alembic environment configuration.

SKILL: Alembic migrations, async database, SQLAlchemy models

This file tells Alembic:
  1. Where the database is (DATABASE_URL from .env)
  2. Which models to inspect (our SQLAlchemy ORM classes)
  3. How to connect (async engine wrapped in sync runner)

When you run 'alembic revision --autogenerate', Alembic:
  - Imports all our models (via target_metadata)
  - Connects to the real database
  - Compares model definitions to actual database tables
  - Generates a migration file with the differences
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# ─────────────────────────────────────────────
# Load our application settings
# ─────────────────────────────────────────────
from app.core.config import settings

# ─────────────────────────────────────────────
# Import Base AND all models
#
# CRITICAL: Every model file MUST be imported here.
# If you create a new model and forget to import it here,
# Alembic will not detect it and will not generate migrations for it.
#
# We import Base from app.db.base (the declarative base).
# We import all model modules so their classes are registered on Base.
# After these imports, Base.metadata contains all table definitions.
# ─────────────────────────────────────────────
from app.db.base import Base
from app.models import workspace    # noqa: F401
from app.models import prompt       # noqa: F401
from app.models import evaluation   # noqa: F401

# ─────────────────────────────────────────────
# Alembic config object — gives access to alembic.ini values
# ─────────────────────────────────────────────
config = context.config

# ─────────────────────────────────────────────
# Configure Python logging from alembic.ini settings
# ─────────────────────────────────────────────
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ─────────────────────────────────────────────
# target_metadata
#
# This is what Alembic compares against the real database.
# Base.metadata contains every table defined in our ORM models.
# Alembic uses this to figure out what needs to be created,
# altered, or dropped.
# ─────────────────────────────────────────────
target_metadata = Base.metadata

# ─────────────────────────────────────────────
# Override the database URL from our settings
# This ensures Alembic always uses the same URL as the app,
# read from .env — not a separately maintained value.
# ─────────────────────────────────────────────
config.set_main_option("sqlalchemy.url", settings.database_url)


def run_migrations_offline() -> None:
    """
    Run migrations without a live database connection.
    Useful for generating SQL scripts to review before running.
    Not commonly used in development, but required by Alembic.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """
    The actual migration runner.
    Called with a live synchronous connection.
    """
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,      # Detect column type changes (e.g. String → Text)
        compare_server_default=True,  # Detect default value changes
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """
    Alembic was built for synchronous databases.
    Our app uses async (asyncpg).

    This function bridges them:
    - Creates an async engine
    - Gets a sync connection from it (using run_sync)
    - Runs migrations synchronously through that connection

    This is the standard pattern for using Alembic with async SQLAlchemy.
    """
    # Create a fresh engine for migrations
    # We use NullPool because Alembic runs migrations as a one-shot script,
    # not a long-running server. No need for connection pooling here.
    connectable = create_async_engine(
        settings.database_url,
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        # run_sync takes an async connection and runs a sync function through it.
        # This is how we use Alembic (sync) with asyncpg (async).
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """
    Entry point for online migration mode (live database).
    This is what runs when you execute 'alembic upgrade head'.
    """
    asyncio.run(run_async_migrations())


# ─────────────────────────────────────────────
# Alembic calls one of these two based on mode.
# In practice, you almost always use "online" mode.
# ─────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()