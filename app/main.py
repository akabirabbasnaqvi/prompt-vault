"""
app/main.py
PromptVault API entry point — Step 11: Structured logging added.
"""

import os
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import pydantic

from app.core.config import settings
from app.core.logging_config import configure_logging
from app.core.cache import redis_client, check_redis_health
from app.db.session import engine, get_db
from app.middleware.logging_middleware import RequestLoggingMiddleware

load_dotenv()

# ── CONFIGURE STRUCTURED LOGGING FIRST ───────────────────────────────
# Must be called before any logger.info() calls anywhere.
# After this, ALL log output is structured JSON.
configure_logging()

logger = logging.getLogger(__name__)


# ── LIFESPAN ──────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Application starting",
        extra={
            "app_name": settings.app_name,
            "version": settings.app_version,
            "debug": settings.debug,
        }
    )

    # Check database
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection verified")
    except Exception as e:
        logger.error("Database connection failed", extra={"error": str(e)})

    # Check Redis
    try:
        await redis_client.ping()
        logger.info("Redis connection verified")
    except Exception as e:
        logger.error("Redis connection failed", extra={"error": str(e)})

    logger.info("PromptVault API ready to accept requests")
    yield

    logger.info("Application shutting down")
    await redis_client.aclose()
    await engine.dispose()
    logger.info("All connections closed")


# ── FASTAPI APP ───────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    description=(
        "PromptVault is an AI prompt lifecycle management API. "
        "Version, test, evaluate, and monitor your LLM prompts "
        "like production code."
    ),
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
    debug=settings.debug,
    lifespan=lifespan,
)

# ── ADD MIDDLEWARE ────────────────────────────────────────────────────
# Middleware is added AFTER app creation, BEFORE routers.
# Order matters: first added = outermost = runs first on request,
# last on response.
app.add_middleware(RequestLoggingMiddleware)


# ── GENERAL ENDPOINTS ─────────────────────────────────────────────────
@app.get("/", summary="Root", tags=["General"])
async def root() -> dict:
    return {
        "message": f"Welcome to {settings.app_name}",
        "version": settings.app_version,
        "status": "running",
        "docs": "/docs",
    }


@app.get("/health", summary="Health check", tags=["General"])
async def health_check(db: AsyncSession = Depends(get_db)) -> JSONResponse:
    health_data = {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
        "python_version": f"{os.sys.version_info.major}.{os.sys.version_info.minor}",
        "pydantic_version": pydantic.VERSION,
        "checks": {
            "database": "unknown",
            "redis": "unknown",
        },
    }

    try:
        await db.execute(text("SELECT 1"))
        health_data["checks"]["database"] = "healthy"
        logger.debug("Health check: database OK")
    except Exception as e:
        health_data["checks"]["database"] = f"unhealthy: {str(e)}"
        health_data["status"] = "degraded"
        logger.warning("Health check: database FAILED", extra={"error": str(e)})

    redis_health = await check_redis_health()
    health_data["checks"]["redis"] = redis_health
    if redis_health["status"] != "healthy":
        health_data["status"] = "degraded"
        logger.warning("Health check: Redis FAILED", extra={"redis": redis_health})

    http_status = 200 if health_data["status"] == "healthy" else 503
    return JSONResponse(content=health_data, status_code=http_status)


@app.get("/api/v1/status", summary="API v1 status", tags=["v1"])
async def api_v1_status() -> dict:
    return {
        "api_version": "v1",
        "status": "active",
        "message": "PromptVault API v1 is ready.",
    }


# ── ROUTERS ───────────────────────────────────────────────────────────
from app.api.v1 import workspaces as workspaces_router
from app.api.v1 import prompts as prompts_router
from app.api.v1 import evaluations as evaluations_router

app.include_router(workspaces_router.router, prefix="/api/v1")
app.include_router(prompts_router.router, prefix="/api/v1")
app.include_router(evaluations_router.router, prefix="/api/v1")