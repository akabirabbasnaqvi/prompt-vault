"""
app/models/evaluation.py

EvaluationJob database model.

SKILL: SQLAlchemy ORM, job tracking pattern

An EvaluationJob tracks:
  - Which prompt is being evaluated
  - What the evaluation result was
  - The current status (pending → running → completed/failed)
  - The Celery task ID (so we can query Celery for progress)
  - Timing information (started_at, completed_at)

WHY STORE JOBS IN THE DATABASE:
  Celery's result backend (Redis) stores results but they expire.
  By also storing in PostgreSQL, we have:
    - Permanent audit trail of all evaluations
    - Query history: "show all evaluations for this prompt"
    - Analytics: "what is the average score for this prompt?"
    - Results survive Redis restarts
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    String, DateTime, ForeignKey, Text,
    Enum, Float, func, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.prompt import Prompt


class JobStatus(str, PyEnum):
    PENDING = "pending"       # Task created, not yet picked up by worker
    RUNNING = "running"       # Worker is actively processing
    COMPLETED = "completed"   # Finished successfully
    FAILED = "failed"         # Finished with an error


class EvaluationJob(Base):
    """
    Tracks a single prompt evaluation job.

    Lifecycle:
      POST /evaluate → job created (status=pending) → Celery task dispatched
      Worker picks up → status=running
      Worker finishes → status=completed, score and result stored
      Worker crashes  → status=failed, error_message stored
    """

    __tablename__ = "evaluation_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # ── LINK TO PROMPT ────────────────────────────────────────────────
    prompt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prompts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── CELERY TASK ID ────────────────────────────────────────────────
    # The ID Celery assigns to the task when we dispatch it.
    # We use this to query Celery for real-time task state.
    # Format: "550e8400-e29b-41d4-a716-446655440000"
    celery_task_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        default=None,
        index=True,
    )

    # ── STATUS ────────────────────────────────────────────────────────
    status: Mapped[JobStatus] = mapped_column(
        Enum(
            JobStatus,
            name="job_status",
            native_enum=False,
            length=20,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=JobStatus.PENDING,
        server_default="pending",
        index=True,
    )

    # ── INPUT ─────────────────────────────────────────────────────────
    # The test input sent to the prompt during evaluation
    test_input: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ── OUTPUT / RESULTS ─────────────────────────────────────────────
    # The raw output from the AI model
    raw_output: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Evaluation score: 0.0 to 1.0
    # How well the prompt performed on this input
    score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    # Human-readable evaluation summary
    evaluation_summary: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Error message if the job failed
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # ── TIMING ───────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── RELATIONSHIPS ─────────────────────────────────────────────────
    prompt: Mapped[Prompt] = relationship(
        "Prompt",
        lazy="select",
    )

    __table_args__ = (
        Index("ix_eval_jobs_prompt_status", "prompt_id", "status"),
        Index("ix_eval_jobs_created", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<EvaluationJob id={self.id} "
            f"status={self.status} score={self.score}>"
        )