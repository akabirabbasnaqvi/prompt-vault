"""
app/services/workspace_service.py

Business logic for workspace operations.

SKILL: Service layer pattern, async SQLAlchemy queries, error handling

WHY A SERVICE LAYER:
  Routes (in api/v1/workspaces.py) handle HTTP concerns:
    - Parse request body
    - Return correct HTTP status codes
    - Call the service

  Services handle business logic:
    - Database queries
    - Data validation beyond schema (e.g. slug uniqueness in DB)
    - Business rules (e.g. cannot delete workspace with active prompts)

  This separation means:
    - You can test business logic without HTTP
    - Routes stay thin and readable
    - Same service can be called from multiple routes or background jobs
"""



"""
app/services/workspace_service.py
Updated in Step 5 to add Redis cache-aside pattern.
"""

import math
import logging
from typing import Optional
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.workspace import Workspace
from app.schemas.workspace import WorkspaceCreate, WorkspaceUpdate
from app.core.cache import (
    cache_get, cache_set, cache_delete, cache_delete_pattern,
    cache_key_workspace, cache_key_workspace_list,
)

logger = logging.getLogger(__name__)


class WorkspaceNotFoundError(Exception):
    pass

class WorkspaceSlugConflictError(Exception):
    pass


async def create_workspace(
    db: AsyncSession,
    data: WorkspaceCreate,
    cache: Optional[Redis] = None,
) -> Workspace:
    logger.info(f"Creating workspace with slug='{data.slug}'")

    existing = await db.execute(
        select(Workspace).where(Workspace.slug == data.slug)
    )
    if existing.scalar_one_or_none() is not None:
        logger.warning(f"Slug conflict: '{data.slug}' already exists")
        raise WorkspaceSlugConflictError(
            f"A workspace with slug '{data.slug}' already exists"
        )

    workspace = Workspace(**data.model_dump())
    db.add(workspace)
    await db.flush()
    await db.refresh(workspace)

    # Invalidate list cache — a new item was added
    if cache:
        await cache_delete_pattern(cache, "workspaces:list:*")

    logger.info(f"Workspace created: id={workspace.id} slug='{workspace.slug}'")
    return workspace


async def get_workspace_by_slug(
    db: AsyncSession,
    slug: str,
    active_only: bool = True,
    cache: Optional[Redis] = None,
) -> Workspace:
    """
    SKILL: Cache-aside pattern in action

    1. Build a deterministic cache key
    2. Check Redis first
    3. On cache hit → deserialize and return (no DB query)
    4. On cache miss → query DB, store in Redis, return
    """
    key = cache_key_workspace(slug)

    # ── CACHE READ ────────────────────────────────────────────────────
    if cache:
        cached = await cache_get(cache, key)
        if cached is not None:
            # We have a cached dict — reconstruct the Workspace ORM object
            # We do this by re-querying with the cached ID so SQLAlchemy
            # tracks the object properly in its session
            workspace_id = cached.get("id")
            if workspace_id:
                result = await db.execute(
                    select(Workspace).where(Workspace.id == workspace_id)
                )
                workspace = result.scalar_one_or_none()
                if workspace:
                    return workspace

    # ── DATABASE READ ─────────────────────────────────────────────────
    query = select(Workspace).where(Workspace.slug == slug)
    if active_only:
        query = query.where(Workspace.is_active == True)

    result = await db.execute(query)
    workspace = result.scalar_one_or_none()

    if workspace is None:
        raise WorkspaceNotFoundError(
            f"Workspace with slug '{slug}' not found"
        )

    # ── CACHE WRITE ───────────────────────────────────────────────────
    if cache:
        await cache_set(cache, key, {
            "id": str(workspace.id),
            "slug": workspace.slug,
            "name": workspace.name,
        })

    return workspace


async def list_workspaces(
    db: AsyncSession,
    page: int = 1,
    size: int = 20,
    active_only: bool = True,
) -> tuple[list[Workspace], int]:
    page = max(1, page)
    size = min(max(1, size), 100)
    offset = (page - 1) * size

    base_query = select(Workspace)
    if active_only:
        base_query = base_query.where(Workspace.is_active == True)

    count_result = await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total = count_result.scalar_one()

    data_result = await db.execute(
        base_query
        .order_by(Workspace.created_at.desc())
        .offset(offset)
        .limit(size)
    )
    workspaces = list(data_result.scalars().all())
    return workspaces, total


async def update_workspace(
    db: AsyncSession,
    slug: str,
    data: WorkspaceUpdate,
    cache: Optional[Redis] = None,
) -> Workspace:
    workspace = await get_workspace_by_slug(db, slug, cache=cache)

    update_data = data.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(workspace, field, value)

    db.add(workspace)
    await db.flush()
    await db.refresh(workspace)

    # Invalidate this workspace's cache entry
    if cache:
        await cache_delete(cache, cache_key_workspace(slug))
        await cache_delete_pattern(cache, "workspaces:list:*")

    logger.info(f"Workspace updated: slug='{slug}'")
    return workspace


async def deactivate_workspace(
    db: AsyncSession,
    slug: str,
    cache: Optional[Redis] = None,
) -> Workspace:
    workspace = await get_workspace_by_slug(db, slug, cache=cache)
    workspace.is_active = False
    db.add(workspace)
    await db.flush()
    await db.refresh(workspace)

    # Invalidate cache
    if cache:
        await cache_delete(cache, cache_key_workspace(slug))
        await cache_delete_pattern(cache, "workspaces:list:*")

    logger.info(f"Workspace deactivated: slug='{slug}'")
    return workspace