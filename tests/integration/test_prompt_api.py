"""
tests/integration/test_prompt_api.py

Integration tests for prompt API endpoints.

SKILL: Nested resource testing, fixture composition,
       status filter query parameter testing
"""

import pytest
from httpx import AsyncClient


class TestCreatePromptEndpoint:
    """Tests for POST /api/v1/workspaces/{slug}/prompts/"""

    async def test_create_prompt_returns_201(
        self, client: AsyncClient, sample_workspace: dict
    ):
        """Creating a prompt should return 201 Created."""
        response = await client.post(
            "/api/v1/workspaces/test-workspace/prompts/",
            json={
                "name": "My Prompt",
                "slug": "my-prompt",
                "description": "Does something",
            },
        )
        assert response.status_code == 201

    async def test_create_prompt_response_shape(
        self, client: AsyncClient, sample_workspace: dict
    ):
        """Response should contain all expected prompt fields."""
        response = await client.post(
            "/api/v1/workspaces/test-workspace/prompts/",
            json={"name": "My Prompt", "slug": "my-prompt"},
        )
        data = response.json()

        assert "id" in data
        assert "workspace_id" in data
        assert "name" in data
        assert "slug" in data
        assert "status" in data
        assert "is_active" in data
        assert data["status"] == "draft"
        assert data["is_active"] is True

    async def test_create_prompt_in_nonexistent_workspace_returns_404(
        self, client: AsyncClient
    ):
        """Creating a prompt in a non-existent workspace should return 404."""
        response = await client.post(
            "/api/v1/workspaces/ghost-workspace/prompts/",
            json={"name": "My Prompt", "slug": "my-prompt"},
        )
        assert response.status_code == 404

    async def test_create_prompt_duplicate_slug_returns_409(
        self, client: AsyncClient, sample_workspace: dict
    ):
        """Duplicate slug within same workspace should return 409."""
        payload = {"name": "My Prompt", "slug": "dup-slug"}

        r1 = await client.post(
            "/api/v1/workspaces/test-workspace/prompts/",
            json=payload,
        )
        assert r1.status_code == 201

        r2 = await client.post(
            "/api/v1/workspaces/test-workspace/prompts/",
            json=payload,
        )
        assert r2.status_code == 409

    async def test_create_prompt_invalid_slug_returns_422(
        self, client: AsyncClient, sample_workspace: dict
    ):
        """Invalid slug should return 422."""
        response = await client.post(
            "/api/v1/workspaces/test-workspace/prompts/",
            json={"name": "My Prompt", "slug": "INVALID SLUG!!"},
        )
        assert response.status_code == 422


class TestGetPromptEndpoint:
    """Tests for GET /api/v1/workspaces/{slug}/prompts/{prompt_slug}"""

    async def test_get_existing_prompt_returns_200(
        self, client: AsyncClient, sample_prompt: dict
    ):
        """Getting an existing prompt should return 200."""
        response = await client.get(
            "/api/v1/workspaces/test-workspace/prompts/test-prompt"
        )
        assert response.status_code == 200
        assert response.json()["slug"] == "test-prompt"

    async def test_get_nonexistent_prompt_returns_404(
        self, client: AsyncClient, sample_workspace: dict
    ):
        """Getting a prompt that does not exist should return 404."""
        response = await client.get(
            "/api/v1/workspaces/test-workspace/prompts/ghost-prompt"
        )
        assert response.status_code == 404


class TestListPromptsEndpoint:
    """Tests for GET /api/v1/workspaces/{slug}/prompts/"""

    async def test_list_prompts_empty(
        self, client: AsyncClient, sample_workspace: dict
    ):
        """Listing prompts when none exist should return empty list."""
        response = await client.get(
            "/api/v1/workspaces/test-workspace/prompts/"
        )
        assert response.status_code == 200
        assert response.json()["total"] == 0

    async def test_list_prompts_returns_created(
        self, client: AsyncClient, sample_prompt: dict
    ):
        """Listing prompts should include created prompt."""
        response = await client.get(
            "/api/v1/workspaces/test-workspace/prompts/"
        )
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["slug"] == "test-prompt"

    async def test_list_prompts_status_filter(
        self, client: AsyncClient, sample_workspace: dict
    ):
        """Status filter should return only prompts with that status."""
        # Create a prompt (default status is draft)
        await client.post(
            "/api/v1/workspaces/test-workspace/prompts/",
            json={"name": "Draft Prompt", "slug": "draft-prompt"},
        )

        # Filter by active — should return none (prompt is draft)
        response = await client.get(
            "/api/v1/workspaces/test-workspace/prompts/?status=active"
        )
        assert response.json()["total"] == 0

        # Filter by draft — should return the prompt
        response = await client.get(
            "/api/v1/workspaces/test-workspace/prompts/?status=draft"
        )
        assert response.json()["total"] == 1


class TestUpdatePromptEndpoint:
    """Tests for PATCH /api/v1/workspaces/{slug}/prompts/{prompt_slug}"""

    async def test_update_prompt_name(
        self, client: AsyncClient, sample_prompt: dict
    ):
        """PATCH should update the prompt name."""
        response = await client.patch(
            "/api/v1/workspaces/test-workspace/prompts/test-prompt",
            json={"name": "Updated Prompt Name"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Updated Prompt Name"

    async def test_update_prompt_status(
        self, client: AsyncClient, sample_prompt: dict
    ):
        """PATCH should allow updating prompt status."""
        response = await client.patch(
            "/api/v1/workspaces/test-workspace/prompts/test-prompt",
            json={"status": "active"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "active"

    async def test_update_nonexistent_prompt_returns_404(
        self, client: AsyncClient, sample_workspace: dict
    ):
        """PATCH on non-existent prompt should return 404."""
        response = await client.patch(
            "/api/v1/workspaces/test-workspace/prompts/ghost",
            json={"name": "New Name"},
        )
        assert response.status_code == 404