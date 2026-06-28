"""
app/services/prompt_service.py
Business logic for Prompt CRUD with Redis caching.
"""

import logging
import math
from typing import Optional
from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.models.prompt import Prompt, PromptStatus
from app.models.workspace import Workspace
from app.schemas.prompt import PromptCreate, PromptUpdate
from app.core.cache import (
    cache_get, cache_set, cache_delete, cache_delete_pattern,
    cache_key_prompt, cache_key_prompt_list,
)

logger = logging.getLogger(__name__)


class PromptNotFoundError(Exception):
    pass

class PromptSlugConflictError(Exception):
    pass

class WorkspaceNotFoundError(Exception):
    pass


async def _get_workspace_or_raise(
    db: AsyncSession,
    workspace_slug: str,
) -> Workspace:
    """Internal helper: get workspace or raise."""
    result = await db.execute(
        select(Workspace)
        .where(Workspace.slug == workspace_slug)
        .where(Workspace.is_active == True)
    )
    workspace = result.scalar_one_or_none()
    if workspace is None:
        raise WorkspaceNotFoundError(
            f"Workspace '{workspace_slug}' not found or inactive"
        )
    return workspace


async def create_prompt(
    db: AsyncSession,
    workspace_slug: str,
    data: PromptCreate,
    cache: Optional[Redis] = None,
) -> Prompt:
    workspace = await _get_workspace_or_raise(db, workspace_slug)

    # Check slug uniqueness within this workspace
    existing = await db.execute(
        select(Prompt)
        .where(Prompt.workspace_id == workspace.id)
        .where(Prompt.slug == data.slug)
    )
    if existing.scalar_one_or_none() is not None:
        raise PromptSlugConflictError(
            f"A prompt with slug '{data.slug}' already exists "
            f"in workspace '{workspace_slug}'"
        )

    prompt = Prompt(
        workspace_id=workspace.id,
        **data.model_dump(),
    )
    db.add(prompt)
    await db.flush()
    await db.refresh(prompt)

    # Invalidate prompt list cache for this workspace
    if cache:
        await cache_delete_pattern(
            cache, f"prompts:{workspace_slug}:*"
        )

    logger.info(
        f"Prompt created: slug='{data.slug}' "
        f"workspace='{workspace_slug}'"
    )
    return prompt


async def get_prompt_by_slug(
    db: AsyncSession,
    workspace_slug: str,
    prompt_slug: str,
    cache: Optional[Redis] = None,
) -> Prompt:
    """Get a prompt with cache-aside."""
    key = cache_key_prompt(workspace_slug, prompt_slug)

    if cache:
        cached = await cache_get(cache, key)
        if cached is not None:
            prompt_id = cached.get("id")
            if prompt_id:
                result = await db.execute(
                    select(Prompt).where(Prompt.id == prompt_id)
                )
                prompt = result.scalar_one_or_none()
                if prompt:
                    return prompt

    # DB query
    workspace = await _get_workspace_or_raise(db, workspace_slug)
    result = await db.execute(
        select(Prompt)
        .where(Prompt.workspace_id == workspace.id)
        .where(Prompt.slug == prompt_slug)
        .where(Prompt.is_active == True)
    )
    prompt = result.scalar_one_or_none()

    if prompt is None:
        raise PromptNotFoundError(
            f"Prompt '{prompt_slug}' not found in workspace '{workspace_slug}'"
        )

    if cache:
        await cache_set(cache, key, {
            "id": str(prompt.id),
            "slug": prompt.slug,
            "workspace_slug": workspace_slug,
        })

    return prompt


async def list_prompts(
    db: AsyncSession,
    workspace_slug: str,
    page: int = 1,
    size: int = 20,
    status_filter: Optional[PromptStatus] = None,
) -> tuple[list[Prompt], int]:
    workspace = await _get_workspace_or_raise(db, workspace_slug)

    page = max(1, page)
    size = min(max(1, size), 100)
    offset = (page - 1) * size

    base_query = (
        select(Prompt)
        .where(Prompt.workspace_id == workspace.id)
        .where(Prompt.is_active == True)
    )
    if status_filter:
        base_query = base_query.where(Prompt.status == status_filter)

    count_result = await db.execute(
        select(func.count()).select_from(base_query.subquery())
    )
    total = count_result.scalar_one()

    data_result = await db.execute(
        base_query
        .order_by(Prompt.created_at.desc())
        .offset(offset)
        .limit(size)
    )
    return list(data_result.scalars().all()), total


async def update_prompt(
    db: AsyncSession,
    workspace_slug: str,
    prompt_slug: str,
    data: PromptUpdate,
    cache: Optional[Redis] = None,
) -> Prompt:
    prompt = await get_prompt_by_slug(
        db, workspace_slug, prompt_slug, cache=cache
    )
    update_data = data.model_dump(exclude_none=True)
    for field, value in update_data.items():
        setattr(prompt, field, value)

    db.add(prompt)
    await db.flush()
    await db.refresh(prompt)

    if cache:
        await cache_delete(cache, cache_key_prompt(workspace_slug, prompt_slug))
        await cache_delete_pattern(cache, f"prompts:{workspace_slug}:*")

    logger.info(f"Prompt updated: '{prompt_slug}' in '{workspace_slug}'")
    return prompt


async def deactivate_prompt(
    db: AsyncSession,
    workspace_slug: str,
    prompt_slug: str,
    cache: Optional[Redis] = None,
) -> Prompt:
    prompt = await get_prompt_by_slug(
        db, workspace_slug, prompt_slug, cache=cache
    )
    prompt.is_active = False
    db.add(prompt)
    await db.flush()
    await db.refresh(prompt)

    if cache:
        await cache_delete(cache, cache_key_prompt(workspace_slug, prompt_slug))
        await cache_delete_pattern(cache, f"prompts:{workspace_slug}:*")

    logger.info(f"Prompt deactivated: '{prompt_slug}' in '{workspace_slug}'")
    return prompt