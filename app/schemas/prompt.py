"""
app/schemas/prompt.py
Pydantic v2 schemas for Prompt API.
"""

import uuid
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
import re

from app.models.prompt import PromptStatus

SLUG_PATTERN = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')


class PromptBase(BaseModel):
    model_config = {"from_attributes": True}


class PromptCreate(PromptBase):
    name: str = Field(..., min_length=2, max_length=255,
                      examples=["Customer Support Summarizer"])
    slug: str = Field(..., min_length=2, max_length=100,
                      examples=["customer-support-summarizer"])
    description: str | None = Field(default=None, max_length=5000)
    tags: str | None = Field(default=None, max_length=500,
                             description="Comma-separated tags",
                             examples=["support,summarization,gpt4"])

    @field_validator("slug")
    @classmethod
    def slug_must_be_valid(cls, v: str) -> str:
        if not SLUG_PATTERN.match(v):
            raise ValueError(
                "Slug must be lowercase letters, numbers, and hyphens only."
            )
        return v

    @field_validator("name")
    @classmethod
    def name_strip(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Name cannot be blank")
        return v.strip()


class PromptUpdate(PromptBase):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=5000)
    tags: str | None = Field(default=None, max_length=500)
    status: PromptStatus | None = Field(default=None)


class PromptResponse(PromptBase):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    slug: str
    description: str | None
    tags: str | None
    status: PromptStatus
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PromptListResponse(PromptBase):
    items: list[PromptResponse]
    total: int
    page: int
    size: int
    pages: int