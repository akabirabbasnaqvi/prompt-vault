"""
app/schemas/workspace.py

Pydantic v2 schemas for Workspace API.

SKILL: Pydantic v2, request/response separation, field validation

Three schema classes per resource is the standard production pattern:

  WorkspaceCreate  → what the CLIENT sends when creating (POST body)
  WorkspaceUpdate  → what the CLIENT sends when updating (PATCH body)
  WorkspaceResponse → what the SERVER sends back (all responses)

WHY THREE SEPARATE CLASSES:
  - Client must NOT set id, created_at, updated_at (server sets these)
  - Client MUST provide name and slug on create (required)
  - Client can optionally change name/description on update (all optional)
  - Response includes all fields including server-generated ones
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
import re


# ─────────────────────────────────────────────────────────────────────
# HELPER: Slug validation
#
# A slug is a URL-safe string: lowercase letters, numbers, hyphens only.
# Examples: "my-team", "acme-ai", "test-workspace-1"
# Invalid:  "My Team", "acme_ai", "test@workspace"
#
# We define this once and reuse it in validators below.
# ─────────────────────────────────────────────────────────────────────
SLUG_PATTERN = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')


def validate_slug_format(slug: str) -> str:
    """
    Validates that a slug:
    - Is lowercase
    - Contains only letters, numbers, and hyphens
    - Does not start or end with a hyphen
    - Is between 2 and 100 characters
    """
    if not SLUG_PATTERN.match(slug):
        raise ValueError(
            "Slug must be lowercase letters, numbers, and hyphens only. "
            "Cannot start or end with a hyphen. Example: 'my-workspace'"
        )
    return slug


# ─────────────────────────────────────────────────────────────────────
# BASE SCHEMA
#
# Shared configuration for all workspace schemas.
# model_config tells Pydantic HOW to behave.
#
# from_attributes=True → allows creating schemas from SQLAlchemy objects.
# Without this, Pydantic cannot read SQLAlchemy model attributes.
# This is REQUIRED for response schemas that receive ORM objects.
# ─────────────────────────────────────────────────────────────────────
class WorkspaceBase(BaseModel):
    model_config = {"from_attributes": True}


# ─────────────────────────────────────────────────────────────────────
# CREATE SCHEMA
#
# Used for: POST /api/v1/workspaces
# The client sends this as the request body.
#
# Field() lets us:
#   - Set min/max length constraints
#   - Add human-readable descriptions (shown in Swagger)
#   - Set examples (shown in Swagger "Try it out")
#   - Mark fields as required (no default) or optional (has default)
# ─────────────────────────────────────────────────────────────────────
class WorkspaceCreate(WorkspaceBase):
    """
    Request body for creating a new workspace.
    All fields except description are required.
    """
    name: str = Field(
        ...,                        # ... means REQUIRED in Pydantic
        min_length=2,
        max_length=255,
        description="Human-readable workspace name",
        examples=["Acme AI Team"],
    )
    slug: str = Field(
        ...,
        min_length=2,
        max_length=100,
        description="URL-safe unique identifier. Lowercase, hyphens only.",
        examples=["acme-ai-team"],
    )
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional workspace description",
        examples=["Prompts for the Acme AI product team"],
    )

    # ── FIELD VALIDATOR ──────────────────────────────────────────────
    # @field_validator runs on a specific field after type conversion.
    # If it raises ValueError, Pydantic returns a 422 with a clear message.
    # ─────────────────────────────────────────────────────────────────
    @field_validator("slug")
    @classmethod
    def slug_must_be_valid(cls, v: str) -> str:
        return validate_slug_format(v)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name cannot be blank or whitespace only")
        return v.strip()  # Remove leading/trailing whitespace


# ─────────────────────────────────────────────────────────────────────
# UPDATE SCHEMA
#
# Used for: PATCH /api/v1/workspaces/{slug}
# ALL fields are optional — client only sends what they want to change.
# This is the PATCH pattern (partial update) vs PUT (full replacement).
#
# In real APIs, PATCH is almost always preferred over PUT because:
#   - Client only sends changed fields (less data)
#   - No risk of accidentally clearing fields the client didn't include
# ─────────────────────────────────────────────────────────────────────
class WorkspaceUpdate(WorkspaceBase):
    """
    Request body for updating a workspace.
    All fields are optional — send only what you want to change.
    """
    name: str | None = Field(
        default=None,
        min_length=2,
        max_length=255,
        description="New workspace name",
    )
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="New workspace description",
    )

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("Name cannot be blank or whitespace only")
        return v.strip() if v else v

    # ── MODEL VALIDATOR ───────────────────────────────────────────────
    # Runs after ALL fields are validated.
    # Used to validate relationships between fields.
    # Here: at least one field must be provided.
    # ─────────────────────────────────────────────────────────────────
    @model_validator(mode="after")
    def at_least_one_field_required(self) -> "WorkspaceUpdate":
        if self.name is None and self.description is None:
            raise ValueError(
                "At least one field (name or description) must be provided"
            )
        return self


# ─────────────────────────────────────────────────────────────────────
# RESPONSE SCHEMA
#
# Used for ALL responses that return workspace data.
# Defines EXACTLY what fields the API exposes to clients.
#
# Notice: is_active is included but internal DB fields like
# the raw UUID format are handled by from_attributes=True.
# ─────────────────────────────────────────────────────────────────────
class WorkspaceResponse(WorkspaceBase):
    """
    API response shape for a workspace.
    This is what clients receive — never raw SQLAlchemy objects.
    """
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    # from_attributes=True is inherited from WorkspaceBase.
    # This means we can do: WorkspaceResponse.model_validate(workspace_orm_object)
    # Pydantic will read attributes from the SQLAlchemy model automatically.


# ─────────────────────────────────────────────────────────────────────
# PAGINATED RESPONSE SCHEMA
#
# SKILL: Pagination design
#
# Never return unlimited lists from an API.
# If you have 10,000 workspaces and a client calls GET /workspaces,
# you would serialize all 10,000 and blow up memory and response time.
#
# Standard pagination response includes:
#   items  → the page of results
#   total  → total count (so client knows how many pages exist)
#   page   → current page number
#   size   → how many items per page
#   pages  → total number of pages
# ─────────────────────────────────────────────────────────────────────
class WorkspaceListResponse(WorkspaceBase):
    """
    Paginated list of workspaces.
    """
    items: list[WorkspaceResponse]
    total: int = Field(description="Total number of workspaces")
    page: int = Field(description="Current page number (1-indexed)")
    size: int = Field(description="Number of items per page")
    pages: int = Field(description="Total number of pages")