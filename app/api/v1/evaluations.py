"""
app/api/v1/evaluations.py
Evaluation job API endpoints.

Routes:
  POST /api/v1/workspaces/{ws}/prompts/{p}/evaluate
       → Trigger a new evaluation job (returns immediately with job_id)

  GET  /api/v1/jobs/{job_id}
       → Poll for job status and results

  GET  /api/v1/workspaces/{ws}/prompts/{p}/evaluations
       → List all evaluation history for a prompt
"""

import logging
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.evaluation import (
    EvaluationCreate,
    EvaluationResponse,
    EvaluationStatusResponse,
)
from app.services.evaluation_service import (
    create_evaluation_job,
    get_job_status,
    list_jobs_for_prompt,
    PromptNotFoundError,
    JobNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Evaluations"])


# ─────────────────────────────────────────────────────────────────────
# POST — Trigger evaluation
#
# This endpoint returns INSTANTLY with a job_id.
# The actual evaluation happens in the background.
# The client polls GET /jobs/{job_id} to check progress.
#
# This pattern is called "async job submission" and is used by:
#   - GitHub Actions (submit workflow → get run_id → poll for status)
#   - AWS Lambda async invocations
#   - Stripe webhook processing
# ─────────────────────────────────────────────────────────────────────
@router.post(
    "/workspaces/{workspace_slug}/prompts/{prompt_slug}/evaluate",
    status_code=status.HTTP_202_ACCEPTED,   # 202 = Accepted for processing
    response_model=EvaluationResponse,
    summary="Trigger a prompt evaluation (async)",
)
async def trigger_evaluation(
    workspace_slug: str,
    prompt_slug: str,
    payload: EvaluationCreate,
    db: AsyncSession = Depends(get_db),
) -> EvaluationResponse:
    """
    Submits a prompt for background evaluation.

    Returns **202 Accepted** immediately with a job record.
    The evaluation runs asynchronously — poll `GET /jobs/{id}` for results.

    HTTP 202 vs 201:
      - 201 Created → resource is fully created and ready
      - 202 Accepted → request accepted, processing will happen later
    """
    try:
        job, task_id = await create_evaluation_job(
            db, workspace_slug, prompt_slug, payload
        )
        logger.info(
            f"Evaluation triggered: job={job.id} task={task_id}"
        )
        return EvaluationResponse.model_validate(job)

    except PromptNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


# ─────────────────────────────────────────────────────────────────────
# GET — Poll job status
#
# Client calls this repeatedly until status is "completed" or "failed".
# Typical polling interval: every 2-3 seconds.
# ─────────────────────────────────────────────────────────────────────
@router.get(
    "/jobs/{job_id}",
    status_code=status.HTTP_200_OK,
    response_model=EvaluationStatusResponse,
    summary="Get evaluation job status",
)
async def get_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
) -> EvaluationStatusResponse:
    """
    Returns the current status of an evaluation job.

    Poll this endpoint after triggering an evaluation.
    When **status** is `completed`, the **score** and **evaluation_summary**
    fields will be populated.
    """
    try:
        job = await get_job_status(db, job_id)

        # Calculate duration if job has completed
        duration = None
        if job.started_at and job.completed_at:
            duration = (
                job.completed_at - job.started_at
            ).total_seconds()

        return EvaluationStatusResponse(
            id=job.id,
            status=job.status,
            score=job.score,
            evaluation_summary=job.evaluation_summary,
            error_message=job.error_message,
            celery_task_id=job.celery_task_id,
            duration_seconds=duration,
        )

    except JobNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid job ID format",
        )


# ─────────────────────────────────────────────────────────────────────
# GET — List evaluation history for a prompt
# ─────────────────────────────────────────────────────────────────────
@router.get(
    "/workspaces/{workspace_slug}/prompts/{prompt_slug}/evaluations",
    status_code=status.HTTP_200_OK,
    response_model=list[EvaluationResponse],
    summary="List evaluation history for a prompt",
)
async def list_evaluations(
    workspace_slug: str,
    prompt_slug: str,
    db: AsyncSession = Depends(get_db),
) -> list[EvaluationResponse]:
    """
    Returns all evaluation jobs for a specific prompt, newest first.
    Use this to see evaluation history and score trends over time.
    """
    try:
        jobs = await list_jobs_for_prompt(db, workspace_slug, prompt_slug)
        return [EvaluationResponse.model_validate(j) for j in jobs]
    except PromptNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )