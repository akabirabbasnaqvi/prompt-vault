"""
tests/integration/test_workspace_api.py

Integration tests for workspace API endpoints.

SKILL: Integration testing, async HTTP testing, HTTP status code verification,
       response schema validation, end-to-end flow testing

Integration tests test the FULL stack:
  HTTP request → FastAPI route → service → database → response

They use a real test database and fake Redis (from conftest.py).
"""

import pytest
from httpx import AsyncClient


class TestCreateWorkspaceEndpoint:
    """Tests for POST /api/v1/workspaces/"""

    async def test_create_workspace_returns_201(self, client: AsyncClient):
        """Creating a workspace should return 201 Created."""
        response = await client.post(
            "/api/v1/workspaces/",
            json={
                "name": "My Workspace",
                "slug": "my-workspace",
                "description": "Test workspace",
            },
        )
        assert response.status_code == 201

    async def test_create_workspace_response_shape(self, client: AsyncClient):
        """Response should contain all expected fields."""
        response = await client.post(
            "/api/v1/workspaces/",
            json={"name": "My Workspace", "slug": "my-workspace"},
        )
        data = response.json()

        assert "id" in data
        assert "name" in data
        assert "slug" in data
        assert "is_active" in data
        assert "created_at" in data
        assert "updated_at" in data
        assert data["name"] == "My Workspace"
        assert data["slug"] == "my-workspace"
        assert data["is_active"] is True

    async def test_create_workspace_duplicate_slug_returns_409(
        self, client: AsyncClient
    ):
        """Creating two workspaces with same slug should return 409 Conflict."""
        payload = {"name": "First", "slug": "duplicate-slug"}

        response1 = await client.post("/api/v1/workspaces/", json=payload)
        assert response1.status_code == 201

        response2 = await client.post("/api/v1/workspaces/", json=payload)
        assert response2.status_code == 409
        assert "duplicate-slug" in response2.json()["detail"]

    async def test_create_workspace_invalid_slug_returns_422(
        self, client: AsyncClient
    ):
        """Invalid slug should return 422 Unprocessable Entity."""
        response = await client.post(
            "/api/v1/workspaces/",
            json={"name": "My Workspace", "slug": "Invalid Slug!!"},
        )
        assert response.status_code == 422

    async def test_create_workspace_missing_name_returns_422(
        self, client: AsyncClient
    ):
        """Missing required field should return 422."""
        response = await client.post(
            "/api/v1/workspaces/",
            json={"slug": "my-workspace"},
        )
        assert response.status_code == 422

    async def test_create_workspace_missing_slug_returns_422(
        self, client: AsyncClient
    ):
        """Missing slug should return 422."""
        response = await client.post(
            "/api/v1/workspaces/",
            json={"name": "My Workspace"},
        )
        assert response.status_code == 422


class TestGetWorkspaceEndpoint:
    """Tests for GET /api/v1/workspaces/{slug}"""

    async def test_get_existing_workspace_returns_200(
        self, client: AsyncClient, sample_workspace: dict
    ):
        """Getting an existing workspace should return 200 OK."""
        slug = sample_workspace["slug"]
        response = await client.get(f"/api/v1/workspaces/{slug}")

        assert response.status_code == 200
        assert response.json()["slug"] == slug

    async def test_get_nonexistent_workspace_returns_404(
        self, client: AsyncClient
    ):
        """Getting a workspace that does not exist should return 404."""
        response = await client.get("/api/v1/workspaces/does-not-exist")
        assert response.status_code == 404

    async def test_get_workspace_response_matches_created(
        self, client: AsyncClient, sample_workspace: dict
    ):
        """GET response should match what was returned on creation."""
        slug = sample_workspace["slug"]
        response = await client.get(f"/api/v1/workspaces/{slug}")
        data = response.json()

        assert data["id"] == sample_workspace["id"]
        assert data["name"] == sample_workspace["name"]
        assert data["slug"] == sample_workspace["slug"]


class TestListWorkspacesEndpoint:
    """Tests for GET /api/v1/workspaces/"""

    async def test_list_empty_returns_200(self, client: AsyncClient):
        """Listing workspaces when none exist should return 200 with empty list."""
        response = await client.get("/api/v1/workspaces/")
        assert response.status_code == 200
        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_list_returns_created_workspace(
        self, client: AsyncClient, sample_workspace: dict
    ):
        """Listing should include the created workspace."""
        response = await client.get("/api/v1/workspaces/")
        data = response.json()

        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["slug"] == sample_workspace["slug"]

    async def test_list_pagination_fields(
        self, client: AsyncClient, sample_workspace: dict
    ):
        """Response should include pagination metadata."""
        response = await client.get("/api/v1/workspaces/?page=1&size=10")
        data = response.json()

        assert "total" in data
        assert "page" in data
        assert "size" in data
        assert "pages" in data
        assert data["page"] == 1
        assert data["size"] == 10

    async def test_list_excludes_inactive_workspaces(
        self, client: AsyncClient, sample_workspace: dict
    ):
        """Soft-deleted workspaces should not appear in list."""
        slug = sample_workspace["slug"]

        # Deactivate it
        delete_response = await client.delete(f"/api/v1/workspaces/{slug}")
        assert delete_response.status_code == 200

        # List should be empty
        list_response = await client.get("/api/v1/workspaces/")
        assert list_response.json()["total"] == 0


class TestUpdateWorkspaceEndpoint:
    """Tests for PATCH /api/v1/workspaces/{slug}"""

    async def test_update_workspace_name(
        self, client: AsyncClient, sample_workspace: dict
    ):
        """PATCH should update only the provided fields."""
        slug = sample_workspace["slug"]
        response = await client.patch(
            f"/api/v1/workspaces/{slug}",
            json={"name": "Updated Name"},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Updated Name"
        assert response.json()["slug"] == slug  # unchanged

    async def test_update_nonexistent_workspace_returns_404(
        self, client: AsyncClient
    ):
        """PATCH on non-existent workspace should return 404."""
        response = await client.patch(
            "/api/v1/workspaces/ghost",
            json={"name": "New Name"},
        )
        assert response.status_code == 404

    async def test_update_with_no_fields_returns_422(
        self, client: AsyncClient, sample_workspace: dict
    ):
        """PATCH with empty body should return 422."""
        slug = sample_workspace["slug"]
        response = await client.patch(
            f"/api/v1/workspaces/{slug}",
            json={},
        )
        assert response.status_code == 422


class TestDeactivateWorkspaceEndpoint:
    """Tests for DELETE /api/v1/workspaces/{slug}"""

    async def test_deactivate_workspace_returns_200(
        self, client: AsyncClient, sample_workspace: dict
    ):
        """DELETE should return 200 with is_active=False."""
        slug = sample_workspace["slug"]
        response = await client.delete(f"/api/v1/workspaces/{slug}")

        assert response.status_code == 200
        assert response.json()["is_active"] is False

    async def test_deactivate_nonexistent_returns_404(
        self, client: AsyncClient
    ):
        """DELETE on non-existent workspace should return 404."""
        response = await client.delete("/api/v1/workspaces/ghost")
        assert response.status_code == 404

    async def test_deactivated_workspace_not_found_on_get(
        self, client: AsyncClient, sample_workspace: dict
    ):
        """After DELETE, GET should return 404."""
        slug = sample_workspace["slug"]

        await client.delete(f"/api/v1/workspaces/{slug}")
        get_response = await client.get(f"/api/v1/workspaces/{slug}")

        assert get_response.status_code == 404