"""
app/core/cache.py

Redis connection and cache-aside helpers.

SKILLS: Redis caching, cache-aside pattern, TTL, cache invalidation,
        async Redis client, JSON serialization for cache storage

This module provides:
  1. An async Redis client (shared across the app)
  2. A FastAPI dependency to inject Redis into routes
  3. Helper functions: get, set, delete cache keys
  4. A health-check function for the /health endpoint
"""

import json
import logging
from typing import Any, AsyncGenerator

import redis.asyncio as aioredis
from redis.asyncio import Redis

from app.core.config import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# REDIS CLIENT SINGLETON
#
# We create ONE Redis client for the entire application.
# Like the SQLAlchemy engine, this manages a connection pool internally.
#
# decode_responses=True → Redis returns Python strings instead of bytes.
#   Without this, every value comes back as b"..." (bytes).
#   With this, values come back as "..." (str). Much easier to work with.
#
# socket_connect_timeout → fail fast if Redis is unreachable
# socket_timeout         → fail fast if a command takes too long
# ─────────────────────────────────────────────────────────────────────
redis_client: Redis = aioredis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=5,
    socket_timeout=5,
    encoding="utf-8",
)


# ─────────────────────────────────────────────────────────────────────
# FASTAPI DEPENDENCY
#
# Just like get_db() provides a database session,
# get_redis() provides the Redis client.
#
# Usage in a route:
#   async def my_route(cache: Redis = Depends(get_redis)):
#       value = await cache_get(cache, "my-key")
#
# We yield (not return) so that future cleanup code can go after yield.
# ─────────────────────────────────────────────────────────────────────
async def get_redis() -> AsyncGenerator[Redis, None]:
    """FastAPI dependency: provides the Redis client."""
    yield redis_client


# ─────────────────────────────────────────────────────────────────────
# CACHE KEY BUILDERS
#
# Cache keys must be:
#   1. Unique — no two different things should share a key
#   2. Predictable — you must be able to reconstruct the key to invalidate
#   3. Namespaced — prefix prevents collisions between different data types
#
# Convention: "resource_type:identifier"
#   "workspace:acme-ai-team"    → single workspace by slug
#   "workspaces:list:page1:20"  → paginated list
#   "prompt:acme-ai-team:summarizer" → single prompt
# ─────────────────────────────────────────────────────────────────────
def cache_key_workspace(slug: str) -> str:
    return f"workspace:{slug}"

def cache_key_workspace_list(page: int, size: int) -> str:
    return f"workspaces:list:page{page}:size{size}"

def cache_key_prompt(workspace_slug: str, prompt_slug: str) -> str:
    return f"prompt:{workspace_slug}:{prompt_slug}"

def cache_key_prompt_list(workspace_slug: str, page: int, size: int) -> str:
    return f"prompts:{workspace_slug}:page{page}:size{size}"


# ─────────────────────────────────────────────────────────────────────
# CACHE OPERATIONS
#
# We store all values as JSON strings.
# WHY JSON: Redis only stores strings. Python dicts, lists, and objects
# must be serialized. JSON is the universal format.
#
# Flow:
#   SET: Python object → json.dumps() → Redis string
#   GET: Redis string  → json.loads() → Python object
# ─────────────────────────────────────────────────────────────────────
async def cache_get(client: Redis, key: str) -> Any | None:
    """
    Retrieve a value from Redis cache.
    Returns the deserialized Python object, or None if not found/expired.

    SKILL: Cache-aside READ path
    """
    try:
        value = await client.get(key)
        if value is None:
            logger.debug(f"Cache MISS: {key}")
            return None
        logger.debug(f"Cache HIT:  {key}")
        return json.loads(value)
    except Exception as e:
        # If Redis is down, log the error but do NOT crash.
        # We fall through to the database query instead.
        # This is called "cache failure graceful degradation" —
        # the app still works, just slower.
        logger.warning(f"Cache GET failed for key '{key}': {e}")
        return None


async def cache_set(
    client: Redis,
    key: str,
    value: Any,
    ttl: int | None = None,
) -> None:
    """
    Store a value in Redis cache with TTL expiry.

    ttl: seconds until this key expires (default: from settings)

    SKILL: Cache-aside WRITE path + TTL
    """
    if ttl is None:
        ttl = settings.redis_ttl_seconds
    try:
        serialized = json.dumps(value, default=str)
        await client.setex(
            name=key,
            time=ttl,        # TTL in seconds — key auto-deletes after this
            value=serialized,
        )
        logger.debug(f"Cache SET:  {key} (TTL={ttl}s)")
    except Exception as e:
        # Again: cache failure should never crash the app.
        logger.warning(f"Cache SET failed for key '{key}': {e}")


async def cache_delete(client: Redis, key: str) -> None:
    """
    Delete a specific key from Redis cache.

    Called when data is modified so next read gets fresh DB data.

    SKILL: Cache invalidation
    """
    try:
        await client.delete(key)
        logger.debug(f"Cache DEL:  {key}")
    except Exception as e:
        logger.warning(f"Cache DELETE failed for key '{key}': {e}")


async def cache_delete_pattern(client: Redis, pattern: str) -> None:
    """
    Delete all keys matching a pattern.
    Used to invalidate list caches when any item in the list changes.

    Example: cache_delete_pattern(client, "workspaces:list:*")
    Deletes: "workspaces:list:page1:size20", "workspaces:list:page2:size20", etc.

    SKILL: Pattern-based cache invalidation
    """
    try:
        # SCAN is safer than KEYS for production — non-blocking
        keys = await client.keys(pattern)
        if keys:
            await client.delete(*keys)
            logger.debug(f"Cache DEL pattern '{pattern}': {len(keys)} keys deleted")
    except Exception as e:
        logger.warning(f"Cache DELETE pattern failed for '{pattern}': {e}")


# ─────────────────────────────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────────────────────────────
async def check_redis_health() -> dict:
    """
    Checks Redis connectivity for the /health endpoint.
    Returns a dict with status and info.
    """
    try:
        pong = await redis_client.ping()
        info = await redis_client.info("server")
        return {
            "status": "healthy",
            "ping": "PONG" if pong else "no response",
            "redis_version": info.get("redis_version", "unknown"),
        }
    except Exception as e:
        return {
            "status": f"unhealthy: {str(e)}",
        }