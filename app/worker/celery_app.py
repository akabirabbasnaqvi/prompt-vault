"""
app/worker/celery_app.py

Celery application configuration.

SKILL: Celery setup, broker/backend configuration, task routing

This file creates the Celery application instance — the equivalent
of FastAPI's `app = FastAPI()` but for background workers.

The Celery app:
  - Connects to Redis as the message broker
  - Connects to Redis as the result backend
  - Discovers tasks automatically from app.worker.tasks
  - Configures serialization, timeouts, and retry behavior
"""

from celery import Celery
from app.core.config import settings

# ─────────────────────────────────────────────────────────────────────
# CELERY APPLICATION INSTANCE
#
# The first argument is the name of the current module.
# This is used for naming auto-generated task names.
# ─────────────────────────────────────────────────────────────────────
celery_app = Celery(
    "promptvault",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.worker.tasks"],   # Modules to import when worker starts
)

# ─────────────────────────────────────────────────────────────────────
# CELERY CONFIGURATION
#
# task_serializer / result_serializer → use JSON (not pickle)
#   JSON is safe and human-readable. Pickle can execute arbitrary code
#   if the message is tampered — a serious security risk.
#   Always use JSON in production.
#
# accept_content → only accept JSON messages (reject anything else)
#
# timezone → always UTC, same as our database timestamps
#
# task_track_started → when a worker picks up a task, immediately
#   update its state to STARTED. Without this, tasks go from PENDING
#   directly to SUCCESS/FAILURE with no intermediate state.
#   This lets us show "processing..." to users.
#
# task_acks_late → acknowledge the message AFTER the task completes,
#   not before. If the worker crashes mid-task, the message goes
#   back to the queue and another worker picks it up.
#   Without this, a crash = lost task with no retry.
#
# worker_prefetch_multiplier → each worker only fetches 1 task at a time.
#   For long-running AI tasks, we don't want a worker hoarding 4 tasks
#   while other workers sit idle.
# ─────────────────────────────────────────────────────────────────────
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,

    # Result expiry: keep results in Redis for 1 hour
    # After this, Redis auto-deletes the result
    result_expires=3600,

    # Task time limits
    # soft limit: task gets a SoftTimeLimitExceeded exception (can clean up)
    # hard limit: task is killed immediately
    task_soft_time_limit=300,    # 5 minutes
    task_time_limit=360,         # 6 minutes

    # Retry configuration
    task_max_retries=3,
    task_default_retry_delay=60,  # seconds between retries
)