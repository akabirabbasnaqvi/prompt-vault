"""
app/api/v1/prompts.py
Prompt REST API endpoints.
Prompts are nested under workspaces: /api/v1/workspaces/{slug}/prompts
"""

import math
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.cache import get_redis
from app.models.prompt import PromptStatus
from app.schemas.prompt import (
    PromptCreate, PromptUpdate,
    PromptResponse, PromptListResponse,
)
from app.services.prompt_service import (
    create_prompt, get_prompt_by_slug, list_prompts,
    update_prompt, deactivate_prompt,
    PromptNotFoundError, PromptSlugConflictError,
    WorkspaceNotFoundError,
)

logger = logging.getLogger(__name__)

# Nested under /api/v1/workspaces/{workspace_slug}/prompts
router = APIRouter(
    prefix="/workspaces/{workspace_slug}/prompts",
    tags=["Prompts"],
)


@router.post("/", status_code=status.HTTP_201_CREATED,
             response_model=PromptResponse)
async def create_prompt_endpoint(
    workspace_slug: str,
    payload: PromptCreate,
    db: AsyncSession = Depends(get_db),
    cache: Redis = Depends(get_redis),
) -> PromptResponse:
    try:
        prompt = await create_prompt(db, workspace_slug, payload, cache=cache)
        return PromptResponse.model_validate(prompt)
    except WorkspaceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))
    except PromptSlugConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.get("/", status_code=status.HTTP_200_OK,
            response_model=PromptListResponse)
async def list_prompts_endpoint(
    workspace_slug: str,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    status_filter: PromptStatus | None = Query(default=None, alias="status"),
    db: AsyncSession = Depends(get_db),
) -> PromptListResponse:
    try:
        prompts, total = await list_prompts(
            db, workspace_slug, page=page,
            size=size, status_filter=status_filter,
        )
        pages = math.ceil(total / size) if total > 0 else 0
        return PromptListResponse(
            items=[PromptResponse.model_validate(p) for p in prompts],
            total=total, page=page, size=size, pages=pages,
        )
    except WorkspaceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.get("/{prompt_slug}", status_code=status.HTTP_200_OK,
            response_model=PromptResponse)
async def get_prompt_endpoint(
    workspace_slug: str,
    prompt_slug: str,
    db: AsyncSession = Depends(get_db),
    cache: Redis = Depends(get_redis),
) -> PromptResponse:
    try:
        prompt = await get_prompt_by_slug(
            db, workspace_slug, prompt_slug, cache=cache
        )
        return PromptResponse.model_validate(prompt)
    except (PromptNotFoundError, WorkspaceNotFoundError) as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.patch("/{prompt_slug}", status_code=status.HTTP_200_OK,
              response_model=PromptResponse)
async def update_prompt_endpoint(
    workspace_slug: str,
    prompt_slug: str,
    payload: PromptUpdate,
    db: AsyncSession = Depends(get_db),
    cache: Redis = Depends(get_redis),
) -> PromptResponse:
    try:
        prompt = await update_prompt(
            db, workspace_slug, prompt_slug, payload, cache=cache
        )
        return PromptResponse.model_validate(prompt)
    except (PromptNotFoundError, WorkspaceNotFoundError) as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete("/{prompt_slug}", status_code=status.HTTP_200_OK,
               response_model=PromptResponse)
async def deactivate_prompt_endpoint(
    workspace_slug: str,
    prompt_slug: str,
    db: AsyncSession = Depends(get_db),
    cache: Redis = Depends(get_redis),
) -> PromptResponse:
    try:
        prompt = await deactivate_prompt(
            db, workspace_slug, prompt_slug, cache=cache
        )
        return PromptResponse.model_validate(prompt)
    except (PromptNotFoundError, WorkspaceNotFoundError) as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))