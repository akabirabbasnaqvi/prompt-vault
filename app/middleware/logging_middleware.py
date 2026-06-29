"""
app/middleware/logging_middleware.py

Request logging middleware with request ID tracing.

SKILL: FastAPI middleware, context variables, request tracing,
       structured logging, performance measurement

This middleware runs for EVERY HTTP request:
  1. Generate a unique request_id (UUID)
  2. Store it in a context variable (accessible anywhere in the request)
  3. Log the incoming request
  4. Let the route handler run
  5. Log the response with status code and duration
  6. Add request_id to the response headers

WHY CONTEXT VARIABLES:
  Python's contextvars module provides variables that are local to
  each async task (each request). When FastAPI handles 100 concurrent
  requests, each gets its own context with its own request_id.
  Your service layer can read the current request_id without it
  being explicitly passed as a function argument.
"""

import time
import uuid
import logging
from contextvars import ContextVar
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# CONTEXT VARIABLE
#
# ContextVar stores a value per-async-task.
# When a request comes in, we set this variable to the request's UUID.
# Any code running in that request's context can read it.
# When 100 requests run concurrently, each has its own value here.
#
# default="" means: if read outside a request context, return empty string
# ─────────────────────────────────────────────────────────────────────
request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def get_request_id() -> str:
    """
    Returns the current request's ID.
    Call this anywhere in your code to get the active request ID.

    Usage in a service:
        from app.middleware.logging_middleware import get_request_id
        logger.info("Processing", extra={"request_id": get_request_id()})
    """
    return request_id_var.get()


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware that logs every HTTP request with timing and request ID.

    Logs two lines per request:
      1. REQUEST  → when the request arrives (method, path, client IP)
      2. RESPONSE → when the response is sent (status code, duration)

    Both lines share the same request_id so you can correlate them.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # ── GENERATE REQUEST ID ───────────────────────────────────────
        # Check if the client sent a request ID (useful when another
        # service calls our API and wants to trace across services).
        # If not, generate a new one.
        request_id = request.headers.get(
            "X-Request-ID",
            str(uuid.uuid4())
        )

        # Store in context variable — accessible anywhere in this request
        token = request_id_var.set(request_id)

        # ── START TIMER ───────────────────────────────────────────────
        start_time = time.perf_counter()

        # ── LOG INCOMING REQUEST ──────────────────────────────────────
        # Skip logging for health checks to reduce noise
        # Health checks are hit every 30 seconds by infrastructure
        is_health_check = request.url.path in ("/health", "/")

        if not is_health_check:
            logger.info(
                "Request started",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "query": str(request.url.query) or None,
                    "client_ip": request.client.host if request.client else None,
                    "user_agent": request.headers.get("user-agent"),
                },
            )

        # ── PROCESS REQUEST ───────────────────────────────────────────
        # Call the next middleware or route handler
        try:
            response = await call_next(request)
        except Exception as exc:
            # Log unhandled exceptions before they propagate
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(
                "Request failed with unhandled exception",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": duration_ms,
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
                exc_info=True,
            )
            raise
        finally:
            # Always reset the context variable
            request_id_var.reset(token)

        # ── CALCULATE DURATION ────────────────────────────────────────
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        # ── LOG RESPONSE ──────────────────────────────────────────────
        if not is_health_check:
            log_level = logging.WARNING if response.status_code >= 400 else logging.INFO

            logger.log(
                log_level,
                "Request completed",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                },
            )

        # ── ADD REQUEST ID TO RESPONSE HEADERS ────────────────────────
        # Clients receive the request_id in the response header.
        # When a user reports a bug, they share this ID and you can
        # search your logs for that exact request.
        response.headers["X-Request-ID"] = request_id

        return response