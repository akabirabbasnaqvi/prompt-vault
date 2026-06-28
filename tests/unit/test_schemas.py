"""
tests/unit/test_schemas.py

Unit tests for Pydantic v2 schemas.

SKILL: Pydantic validation testing, pytest unit tests

Unit tests are fast and focused — they test ONE thing in isolation.
No database, no HTTP, no Redis. Just Python objects.

These tests verify that:
- Valid data passes validation
- Invalid data raises ValidationError with the right message
- Custom validators (slug format, blank name) work correctly
"""

import pytest
from pydantic import ValidationError
from app.schemas.workspace import WorkspaceCreate, WorkspaceUpdate
from app.schemas.prompt import PromptCreate


class TestWorkspaceCreateSchema:
    """Tests for WorkspaceCreate Pydantic schema."""

    def test_valid_workspace_create(self):
        """Valid data should create a WorkspaceCreate without errors."""
        workspace = WorkspaceCreate(
            name="My Team",
            slug="my-team",
            description="A great team",
        )
        assert workspace.name == "My Team"
        assert workspace.slug == "my-team"
        assert workspace.description == "A great team"

    def test_valid_workspace_without_description(self):
        """Description is optional — should work without it."""
        workspace = WorkspaceCreate(
            name="My Team",
            slug="my-team",
        )
        assert workspace.description is None

    def test_slug_with_uppercase_fails(self):
        """Slug must be lowercase — uppercase should raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            WorkspaceCreate(name="My Team", slug="My-Team")
        # Verify the error message mentions the slug format
        assert "lowercase" in str(exc_info.value).lower() or \
               "slug" in str(exc_info.value).lower()

    def test_slug_with_spaces_fails(self):
        """Spaces in slug should fail validation."""
        with pytest.raises(ValidationError):
            WorkspaceCreate(name="My Team", slug="my team")

    def test_slug_with_special_chars_fails(self):
        """Special characters in slug should fail."""
        with pytest.raises(ValidationError):
            WorkspaceCreate(name="My Team", slug="my@team!")

    def test_slug_starting_with_hyphen_fails(self):
        """Slug cannot start with a hyphen."""
        with pytest.raises(ValidationError):
            WorkspaceCreate(name="My Team", slug="-my-team")

    def test_slug_ending_with_hyphen_fails(self):
        """Slug cannot end with a hyphen."""
        with pytest.raises(ValidationError):
            WorkspaceCreate(name="My Team", slug="my-team-")

    def test_blank_name_fails(self):
        """Whitespace-only name should fail validation."""
        with pytest.raises(ValidationError):
            WorkspaceCreate(name="   ", slug="my-team")

    def test_name_is_stripped(self):
        """Leading/trailing whitespace should be stripped from name."""
        workspace = WorkspaceCreate(
            name="  My Team  ",
            slug="my-team",
        )
        assert workspace.name == "My Team"

    def test_name_too_short_fails(self):
        """Name shorter than 2 characters should fail."""
        with pytest.raises(ValidationError):
            WorkspaceCreate(name="A", slug="my-team")

    def test_slug_too_short_fails(self):
        """Slug shorter than 2 characters should fail."""
        with pytest.raises(ValidationError):
            WorkspaceCreate(name="My Team", slug="a")

    def test_valid_slug_formats(self):
        """Various valid slug formats should all pass."""
        valid_slugs = [
            "my-team",
            "myteam",
            "my-team-123",
            "123-team",
            "team123",
        ]
        for slug in valid_slugs:
            workspace = WorkspaceCreate(name="My Team", slug=slug)
            assert workspace.slug == slug


class TestWorkspaceUpdateSchema:
    """Tests for WorkspaceUpdate Pydantic schema."""

    def test_update_name_only(self):
        """Should allow updating just the name."""
        update = WorkspaceUpdate(name="New Name")
        assert update.name == "New Name"
        assert update.description is None

    def test_update_description_only(self):
        """Should allow updating just the description."""
        update = WorkspaceUpdate(description="New description")
        assert update.description == "New description"
        assert update.name is None

    def test_empty_update_fails(self):
        """At least one field must be provided."""
        with pytest.raises(ValidationError) as exc_info:
            WorkspaceUpdate()
        assert "at least one field" in str(exc_info.value).lower()

    def test_blank_name_fails(self):
        """Blank name in update should fail."""
        with pytest.raises(ValidationError):
            WorkspaceUpdate(name="   ")


class TestPromptCreateSchema:
    """Tests for PromptCreate Pydantic schema."""

    def test_valid_prompt_create(self):
        """Valid prompt data should pass validation."""
        prompt = PromptCreate(
            name="My Prompt",
            slug="my-prompt",
            description="Does something useful",
            tags="tag1,tag2",
        )
        assert prompt.name == "My Prompt"
        assert prompt.slug == "my-prompt"

    def test_invalid_slug_fails(self):
        """Invalid slug format should raise ValidationError."""
        with pytest.raises(ValidationError):
            PromptCreate(name="My Prompt", slug="My Prompt!")

    def test_prompt_without_optional_fields(self):
        """Prompt with only required fields should pass."""
        prompt = PromptCreate(
            name="My Prompt",
            slug="my-prompt",
        )
        assert prompt.description is None
        assert prompt.tags is None