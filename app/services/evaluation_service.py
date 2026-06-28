"""
app/services/evaluation_service.py
Business logic for creating and querying evaluation jobs.
"""

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.evaluation import EvaluationJob, JobStatus
from app.models.prompt import Prompt
from app.schemas.evaluation import EvaluationCreate

logger = logging.getLogger(__name__)


class PromptNotFoundError(Exception):
    pass

class JobNotFoundError(Exception):
    pass


async def create_evaluation_job(
    db: AsyncSession,
    workspace_slug: str,
    prompt_slug: str,
    data: EvaluationCreate,
) -> tuple[EvaluationJob, str]:
    """
    Creates an EvaluationJob record and dispatches a Celery task.

    Returns: (job, celery_task_id)

    WHY CREATE THE DB RECORD FIRST:
      We create the database record before dispatching the Celery task.
      This ensures:
        1. We always have a record of the job, even if Celery is down
        2. The client gets a job_id to poll immediately
        3. If the task dispatch fails, the job shows as PENDING
           and can be retried
    """
    from app.models.workspace import Workspace
    from app.worker.tasks import evaluate_prompt_task

    # Verify workspace exists
    ws_result = await db.execute(
        select(Workspace)
        .where(Workspace.slug == workspace_slug)
        .where(Workspace.is_active == True)
    )
    workspace = ws_result.scalar_one_or_none()
    if workspace is None:
        raise PromptNotFoundError(
            f"Workspace '{workspace_slug}' not found"
        )

    # Verify prompt exists
    prompt_result = await db.execute(
        select(Prompt)
        .where(Prompt.workspace_id == workspace.id)
        .where(Prompt.slug == prompt_slug)
        .where(Prompt.is_active == True)
    )
    prompt = prompt_result.scalar_one_or_none()
    if prompt is None:
        raise PromptNotFoundError(
            f"Prompt '{prompt_slug}' not found in workspace '{workspace_slug}'"
        )

    # ── CREATE JOB RECORD ─────────────────────────────────────────────
    job = EvaluationJob(
        prompt_id=prompt.id,
        test_input=data.test_input,
        status=JobStatus.PENDING,
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)

    logger.info(
        f"Evaluation job created: id={job.id} "
        f"prompt='{prompt_slug}'"
    )

    # ── DISPATCH CELERY TASK ──────────────────────────────────────────
    # .delay() is shorthand for .apply_async()
    # It sends the task to the Redis broker queue.
    # The Celery worker will pick it up and execute it.
    #
    # We pass primitive types (str) not complex objects (UUID, ORM models)
    # because Celery serializes arguments to JSON.
    # UUIDs must be converted to strings.
    celery_task = evaluate_prompt_task.delay(
        job_id=str(job.id),
        prompt_id=str(prompt.id),
        test_input=data.test_input,
    )

    # Store the Celery task ID so we can query Celery for real-time state
    job.celery_task_id = celery_task.id
    db.add(job)
    await db.flush()
    await db.refresh(job)

    logger.info(
        f"Celery task dispatched: task_id={celery_task.id}"
    )

    return job, celery_task.id


async def get_job_status(
    db: AsyncSession,
    job_id: str,
) -> EvaluationJob:
    """
    Gets the current status of an evaluation job.
    Combines database status with real-time Celery state.
    """
    result = await db.execute(
        select(EvaluationJob).where(
            EvaluationJob.id == UUID(job_id)
        )
    )
    job = result.scalar_one_or_none()

    if job is None:
        raise JobNotFoundError(f"Job '{job_id}' not found")

    return job


async def list_jobs_for_prompt(
    db: AsyncSession,
    workspace_slug: str,
    prompt_slug: str,
) -> list[EvaluationJob]:
    """Lists all evaluation jobs for a specific prompt."""
    from app.models.workspace import Workspace

    ws_result = await db.execute(
        select(Workspace)
        .where(Workspace.slug == workspace_slug)
        .where(Workspace.is_active == True)
    )
    workspace = ws_result.scalar_one_or_none()
    if not workspace:
        raise PromptNotFoundError(f"Workspace '{workspace_slug}' not found")

    prompt_result = await db.execute(
        select(Prompt)
        .where(Prompt.workspace_id == workspace.id)
        .where(Prompt.slug == prompt_slug)
    )
    prompt = prompt_result.scalar_one_or_none()
    if not prompt:
        raise PromptNotFoundError(
            f"Prompt '{prompt_slug}' not found"
        )

    jobs_result = await db.execute(
        select(EvaluationJob)
        .where(EvaluationJob.prompt_id == prompt.id)
        .order_by(EvaluationJob.created_at.desc())
        .limit(50)
    )
    return list(jobs_result.scalars().all())