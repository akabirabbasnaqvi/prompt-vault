"""
app/core/config.py

Centralised configuration using Pydantic Settings.

SKILL: Pydantic v2 BaseSettings
WHY: Instead of scattered os.getenv() calls all over the codebase,
     we define ALL configuration in one class. Pydantic automatically:
     - Reads values from the .env file
     - Validates types (e.g. DB_POOL_SIZE must be an integer)
     - Raises a clear error on startup if a required value is missing
     - Provides type hints for IDE autocomplete everywhere

This is the standard pattern used in production FastAPI applications.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    """
    All application settings are defined here as typed fields.

    Pydantic reads these from environment variables (or .env file).
    The field name is the environment variable name (case-insensitive).

    Example: APP_NAME in .env → settings.app_name in Python
    """

    # ── Application ──────────────────────────────────────────────────
    app_name: str = "PromptVault"
    app_version: str = "0.1.0"
    debug: bool = False

    # ── Database ─────────────────────────────────────────────────────
    # This field is REQUIRED — no default value.
    # If DATABASE_URL is missing from .env, the app will REFUSE to start
    # with a clear error. This prevents silent misconfiguration.
    database_url: str


    # ── Redis ─────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"
    redis_ttl_seconds: int = 300        # Cache TTL: 5 minutes

    # Connection pool settings
    # Pool size = number of persistent connections kept open
    # Max overflow = extra connections allowed when pool is full
    # Pool timeout = seconds to wait for a connection before raising an error
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: int = 30


    # ── Celery ────────────────────────────────────────────────────────────
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # ── Pydantic Settings Configuration ──────────────────────────────
    model_config = SettingsConfigDict(
        env_file=".env",           # Read from this file
        env_file_encoding="utf-8", # File encoding
        case_sensitive=False,      # DATABASE_URL and database_url are the same
    )


# ─────────────────────────────────────────────────────────────────────
# Singleton pattern using lru_cache
#
# @lru_cache means this function is only executed ONCE.
# Every time get_settings() is called anywhere in the app,
# it returns the SAME Settings object (not a new one each time).
#
# WHY THIS MATTERS:
# Reading .env files and validating all settings takes time.
# We do it once at startup, then reuse the result.
# This is called the Singleton pattern — one instance shared everywhere.
# ─────────────────────────────────────────────────────────────────────
@lru_cache
def get_settings() -> Settings:
    """
    Returns the application settings singleton.
    Call this function anywhere you need settings.

    Usage:
        from app.core.config import get_settings
        settings = get_settings()
        print(settings.app_name)
    """
    return Settings()


# ─────────────────────────────────────────────────────────────────────
# Module-level settings instance
# Import this directly for convenience:
#   from app.core.config import settings
# ─────────────────────────────────────────────────────────────────────
settings = get_settings()