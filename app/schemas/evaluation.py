"""
app/schemas/evaluation.py
Pydantic schemas for EvaluationJob API.
"""

import uuid
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field
from app.models.evaluation import JobStatus


class EvaluationBase(BaseModel):
    model_config = {"from_attributes": True}


class EvaluationCreate(EvaluationBase):
    """Request body to trigger a prompt evaluation."""
    test_input: str = Field(
        ...,
        min_length=1,
        max_length=5000,
        description="The test input to evaluate the prompt with",
        examples=["Summarize this customer complaint: The product arrived broken."],
    )


class EvaluationResponse(EvaluationBase):
    """Response after triggering an evaluation job."""
    id: uuid.UUID
    prompt_id: uuid.UUID
    celery_task_id: str | None
    status: JobStatus
    test_input: str | None
    raw_output: str | None
    score: float | None
    evaluation_summary: str | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


class EvaluationStatusResponse(EvaluationBase):
    """
    Lightweight status check response.
    Used for polling: client checks this repeatedly until status=completed.
    """
    id: uuid.UUID
    status: JobStatus
    score: float | None
    evaluation_summary: str | None
    error_message: str | None
    celery_task_id: str | None

    # Computed field: processing duration in seconds
    duration_seconds: float | None = None