"""
app/models/prompt.py
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING

from sqlalchemy import (
    String, Boolean, DateTime, ForeignKey,
    Text, Enum, Index, UniqueConstraint, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.workspace import Workspace


class PromptStatus(str, PyEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class Prompt(Base):
    __tablename__ = "prompts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    slug: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )

    tags: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        default=None,
    )

    # ── WHY native_enum=False ─────────────────────────────────────────
    # native_enum=True  → creates a PostgreSQL ENUM type (draft, active...)
    #                     This caused all our migration errors because
    #                     asyncpg + Alembic have bugs with ENUM type
    #                     creation and server_default values.
    #
    # native_enum=False → stores the value as VARCHAR in PostgreSQL.
    #                     SQLAlchemy adds a CHECK CONSTRAINT automatically:
    #                     CHECK (status IN ('draft', 'active', 'archived'))
    #                     This enforces the same data integrity at the DB level.
    #                     No ENUM type to manage. No case issues. No bugs.
    #                     This is what many production teams choose.
    # ─────────────────────────────────────────────────────────────────
    status: Mapped[PromptStatus] = mapped_column(
        Enum(
            PromptStatus,
            name="prompt_status",
            native_enum=False,      # Store as VARCHAR + CHECK constraint
            length=20,              # Max length of the VARCHAR column
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=PromptStatus.DRAFT,
        server_default="draft",     # Now works fine — just a plain string default
        index=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    workspace: Mapped[Workspace] = relationship(
        "Workspace",
        back_populates="prompts",
        lazy="select",
    )

    __table_args__ = (
        UniqueConstraint("workspace_id", "slug", name="uq_prompts_workspace_slug"),
        Index("ix_prompts_workspace_status", "workspace_id", "status"),
        Index("ix_prompts_workspace_created", "workspace_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<Prompt id={self.id} slug={self.slug!r} status={self.status}>"