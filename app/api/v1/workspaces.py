"""
app/api/v1/workspaces.py

REST API routes for workspace operations.

SKILL: FastAPI routing, HTTP status codes, dependency injection,
       exception handling, response models, pagination query params

This file is thin by design.
Routes handle HTTP: parse input, call service, return response.
Services handle logic: queries, business rules, exceptions.
"""

"""
app/api/v1/workspaces.py
Updated in Step 5 to inject Redis cache into service calls.
"""

import math
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.core.cache import get_redis
from app.schemas.workspace import (
    WorkspaceCreate, WorkspaceUpdate,
    WorkspaceResponse, WorkspaceListResponse,
)
from app.services.workspace_service import (
    create_workspace, get_workspace_by_slug,
    list_workspaces, update_workspace, deactivate_workspace,
    WorkspaceNotFoundError, WorkspaceSlugConflictError,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces", tags=["Workspaces"])


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=WorkspaceResponse)
async def create_workspace_endpoint(
    payload: WorkspaceCreate,
    db: AsyncSession = Depends(get_db),
    cache: Redis = Depends(get_redis),       # ← Redis injected here
) -> WorkspaceResponse:
    try:
        workspace = await create_workspace(db, payload, cache=cache)
        return WorkspaceResponse.model_validate(workspace)
    except WorkspaceSlugConflictError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))


@router.get("/", status_code=status.HTTP_200_OK, response_model=WorkspaceListResponse)
async def list_workspaces_endpoint(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceListResponse:
    workspaces, total = await list_workspaces(db, page=page, size=size)
    pages = math.ceil(total / size) if total > 0 else 0
    return WorkspaceListResponse(
        items=[WorkspaceResponse.model_validate(w) for w in workspaces],
        total=total, page=page, size=size, pages=pages,
    )


@router.get("/{slug}", status_code=status.HTTP_200_OK, response_model=WorkspaceResponse)
async def get_workspace_endpoint(
    slug: str,
    db: AsyncSession = Depends(get_db),
    cache: Redis = Depends(get_redis),       # ← Cache checked first
) -> WorkspaceResponse:
    try:
        workspace = await get_workspace_by_slug(db, slug, cache=cache)
        return WorkspaceResponse.model_validate(workspace)
    except WorkspaceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.patch("/{slug}", status_code=status.HTTP_200_OK, response_model=WorkspaceResponse)
async def update_workspace_endpoint(
    slug: str,
    payload: WorkspaceUpdate,
    db: AsyncSession = Depends(get_db),
    cache: Redis = Depends(get_redis),
) -> WorkspaceResponse:
    try:
        workspace = await update_workspace(db, slug, payload, cache=cache)
        return WorkspaceResponse.model_validate(workspace)
    except WorkspaceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))


@router.delete("/{slug}", status_code=status.HTTP_200_OK, response_model=WorkspaceResponse)
async def deactivate_workspace_endpoint(
    slug: str,
    db: AsyncSession = Depends(get_db),
    cache: Redis = Depends(get_redis),
) -> WorkspaceResponse:
    try:
        workspace = await deactivate_workspace(db, slug, cache=cache)
        return WorkspaceResponse.model_validate(workspace)
    except WorkspaceNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e))