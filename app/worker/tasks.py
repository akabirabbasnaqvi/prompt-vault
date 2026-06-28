"""
app/worker/tasks.py

Celery background tasks.

SKILL: Celery tasks, async-to-sync bridge, database in workers,
       task states (PENDING → STARTED → SUCCESS/FAILURE),
       simulated AI evaluation (free — no API key needed)

WHY SIMULATION INSTEAD OF REAL AI:
  We simulate the AI evaluation with a rule-based scorer.
  This lets you:
    - Build and understand the full pipeline for free
    - See real async behavior with realistic delays
    - Replace the simulator with real AI (OpenAI, Ollama, etc.) later
    - The architecture is identical whether using real AI or simulation

HOW CELERY TASKS WORK WITH DATABASES:
  Celery workers are separate processes from FastAPI.
  They do not share the FastAPI app instance or its database sessions.
  Each task must create its own database connection.
  We use synchronous SQLAlchemy here (not async) because Celery
  workers are synchronous by default. This is the standard pattern.
"""

import time
import random
import logging
from datetime import datetime, timezone
from uuid import UUID

from celery import Task
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, Session

from app.worker.celery_app import celery_app
from app.core.config import settings
from app.models.evaluation import EvaluationJob, JobStatus
from app.models.prompt import Prompt

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# SYNCHRONOUS DATABASE ENGINE FOR CELERY WORKERS
#
# IMPORTANT: Celery workers are synchronous processes.
# We cannot use the async SQLAlchemy engine from app/db/session.py here.
# We create a separate synchronous engine specifically for tasks.
#
# We convert the async URL to sync URL:
#   postgresql+asyncpg://...  →  postgresql+psycopg2://...
#
# psycopg2 is the standard synchronous PostgreSQL driver for Python.
# ─────────────────────────────────────────────────────────────────────
sync_database_url = settings.database_url.replace(
    "postgresql+asyncpg://",
    "postgresql+psycopg2://",
)

# Install psycopg2 if not already installed
# (we add it to requirements in the install step)
sync_engine = create_engine(
    sync_database_url,
    pool_size=5,
    pool_pre_ping=True,
    echo=False,    # Don't log SQL in workers (too noisy)
)

SyncSessionLocal = sessionmaker(
    bind=sync_engine,
    autocommit=False,
    autoflush=False,
)


def get_sync_db() -> Session:
    """Get a synchronous database session for use in Celery tasks."""
    return SyncSessionLocal()


# ─────────────────────────────────────────────────────────────────────
# PROMPT EVALUATOR (FREE SIMULATION)
#
# In a real system, this would call OpenAI, Claude, or a local model.
# Our simulator:
#   1. Checks prompt quality heuristics (length, keywords, structure)
#   2. Adds realistic processing delay (simulates AI inference time)
#   3. Returns a score and detailed feedback
#
# This gives you the EXACT same architecture as a real AI evaluator.
# When you have API credits, you replace simulate_evaluation() only.
# Everything else stays the same.
# ─────────────────────────────────────────────────────────────────────
def simulate_evaluation(
    prompt_name: str,
    prompt_description: str | None,
    test_input: str,
) -> dict:
    """
    Simulates AI evaluation of a prompt.
    Returns a score (0.0-1.0) and detailed feedback.

    Scoring heuristics:
      - Prompt has a description: +0.2
      - Test input is substantial (>20 chars): +0.2
      - Prompt name contains action words: +0.2
      - Random variance to simulate real model variance: +/- 0.2
      - Base score: 0.4
    """
    logger.info(f"Evaluating prompt: '{prompt_name}'")

    # Simulate AI processing time (2-5 seconds)
    processing_time = random.uniform(2.0, 5.0)
    time.sleep(processing_time)

    # Score calculation
    score = 0.4  # base score

    if prompt_description and len(prompt_description) > 20:
        score += 0.2  # Has meaningful description

    if len(test_input) > 20:
        score += 0.2  # Substantial test input

    action_words = ["summarize", "analyze", "generate", "classify",
                    "extract", "evaluate", "compare", "explain"]
    if any(word in prompt_name.lower() for word in action_words):
        score += 0.2  # Prompt has clear action verb

    # Add realistic variance
    variance = random.uniform(-0.1, 0.1)
    score = max(0.0, min(1.0, score + variance))

    # Generate feedback
    if score >= 0.8:
        quality = "excellent"
        feedback = (
            f"This prompt demonstrates excellent clarity and specificity. "
            f"The action is well-defined and the expected output is clear. "
            f"Processing completed in {processing_time:.1f}s."
        )
    elif score >= 0.6:
        quality = "good"
        feedback = (
            f"This prompt performs well with good structure. "
            f"Consider adding more specific output format requirements "
            f"to improve consistency. Processed in {processing_time:.1f}s."
        )
    else:
        quality = "needs improvement"
        feedback = (
            f"This prompt could benefit from clearer instructions and "
            f"more specific expected outputs. Consider adding examples. "
            f"Processed in {processing_time:.1f}s."
        )

    return {
        "raw_output": f"[Simulated AI Output]\nInput: {test_input}\nAnalysis: {quality.title()} prompt quality detected.",
        "score": round(score, 3),
        "evaluation_summary": feedback,
    }


# ─────────────────────────────────────────────────────────────────────
# CELERY TASK
#
# @celery_app.task(bind=True) → bind=True gives us access to `self`
# which is the Task instance. We use it to:
#   - Update task state (self.update_state)
#   - Retry on failure (self.retry)
#   - Access task ID (self.request.id)
#
# TASK STATES:
#   PENDING   → task is in the queue, not yet started
#   STARTED   → worker picked it up (requires task_track_started=True)
#   RETRY     → task failed and will be retried
#   SUCCESS   → task completed successfully
#   FAILURE   → task failed permanently
#
# These states are stored in the Redis result backend and can be
# queried at any time via celery_app.AsyncResult(task_id).state
# ─────────────────────────────────────────────────────────────────────
@celery_app.task(
    bind=True,
    name="evaluate_prompt",
    max_retries=3,
    default_retry_delay=30,
)
def evaluate_prompt_task(
    self: Task,
    job_id: str,
    prompt_id: str,
    test_input: str,
) -> dict:
    """
    Background task: evaluates a prompt and stores results.

    Arguments:
        job_id    → UUID of the EvaluationJob record in our database
        prompt_id → UUID of the Prompt being evaluated
        test_input → the test input string to evaluate the prompt with

    Returns:
        dict with score, summary, and status

    FLOW:
        1. Update job status to RUNNING in database
        2. Fetch the prompt from database
        3. Run evaluation (simulate AI inference)
        4. Update job with results and status=COMPLETED
        5. If anything fails → update status=FAILED and retry
    """
    db = get_sync_db()
    logger.info(
        f"Task {self.request.id} starting: "
        f"job_id={job_id} prompt_id={prompt_id}"
    )

    try:
        # ── STEP 1: Mark job as RUNNING ───────────────────────────────
        job = db.execute(
            select(EvaluationJob).where(
                EvaluationJob.id == UUID(job_id)
            )
        ).scalar_one()

        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(timezone.utc)
        job.celery_task_id = self.request.id
        db.commit()

        # Update Celery state so the client can see "RUNNING"
        self.update_state(
            state="PROGRESS",
            meta={"job_id": job_id, "status": "running"},
        )

        # ── STEP 2: Fetch the prompt ───────────────────────────────────
        prompt = db.execute(
            select(Prompt).where(Prompt.id == UUID(prompt_id))
        ).scalar_one()

        logger.info(
            f"Task {self.request.id}: evaluating prompt '{prompt.slug}'"
        )

        # ── STEP 3: Run evaluation ─────────────────────────────────────
        result = simulate_evaluation(
            prompt_name=prompt.name,
            prompt_description=prompt.description,
            test_input=test_input,
        )

        # ── STEP 4: Store results ──────────────────────────────────────
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc)
        job.raw_output = result["raw_output"]
        job.score = result["score"]
        job.evaluation_summary = result["evaluation_summary"]
        db.commit()

        logger.info(
            f"Task {self.request.id} completed: "
            f"score={result['score']}"
        )

        return {
            "job_id": job_id,
            "status": "completed",
            "score": result["score"],
            "summary": result["evaluation_summary"],
        }

    except Exception as exc:
        # ── STEP 5: Handle failure ─────────────────────────────────────
        logger.error(
            f"Task {self.request.id} failed: {exc}",
            exc_info=True,
        )

        try:
            # Update job status to FAILED in database
            job = db.execute(
                select(EvaluationJob).where(
                    EvaluationJob.id == UUID(job_id)
                )
            ).scalar_one_or_none()

            if job:
                job.status = JobStatus.FAILED
                job.completed_at = datetime.now(timezone.utc)
                job.error_message = str(exc)
                db.commit()
        except Exception as db_exc:
            logger.error(f"Failed to update job status: {db_exc}")

        # Retry the task if we haven't hit max_retries
        # self.retry() raises a Retry exception — do NOT catch it
        raise self.retry(exc=exc, countdown=30)

    finally:
        db.close()