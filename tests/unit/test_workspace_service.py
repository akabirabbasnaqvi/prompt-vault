"""
tests/unit/test_workspace_service.py

Unit tests for workspace service functions.

SKILL: Async unit tests, mocking database sessions,
       testing business logic in isolation

These tests use a REAL test database session (from conftest.py)
but mock Redis to keep tests fast and isolated.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.workspace_service import (
    create_workspace,
    get_workspace_by_slug,
    update_workspace,
    deactivate_workspace,
    WorkspaceNotFoundError,
    WorkspaceSlugConflictError,
)
from app.schemas.workspace import WorkspaceCreate, WorkspaceUpdate


class TestCreateWorkspace:
    """Tests for create_workspace service function."""

    async def test_create_workspace_success(
        self,
        db_session: AsyncSession,
        fake_redis,
    ):
        """Creating a workspace with valid data should succeed."""
        data = WorkspaceCreate(
            name="Test Workspace",
            slug="test-workspace",
            description="A test workspace",
        )

        workspace = await create_workspace(db_session, data, cache=fake_redis)

        assert workspace.id is not None
        assert workspace.name == "Test Workspace"
        assert workspace.slug == "test-workspace"
        assert workspace.is_active is True
        assert workspace.created_at is not None

    async def test_create_workspace_duplicate_slug_raises(
        self,
        db_session: AsyncSession,
        fake_redis,
    ):
        """Creating two workspaces with the same slug should raise conflict error."""
        data = WorkspaceCreate(name="First", slug="same-slug")

        await create_workspace(db_session, data, cache=fake_redis)
        await db_session.commit()

        with pytest.raises(WorkspaceSlugConflictError) as exc_info:
            await create_workspace(
                db_session,
                WorkspaceCreate(name="Second", slug="same-slug"),
                cache=fake_redis,
            )
        assert "same-slug" in str(exc_info.value)

    async def test_create_workspace_without_description(
        self,
        db_session: AsyncSession,
    ):
        """Creating a workspace without description should set it to None."""
        data = WorkspaceCreate(name="No Desc", slug="no-desc")
        workspace = await create_workspace(db_session, data)

        assert workspace.description is None


class TestGetWorkspaceBySlug:
    """Tests for get_workspace_by_slug service function."""

    async def test_get_existing_workspace(
        self,
        db_session: AsyncSession,
        fake_redis,
    ):
        """Getting an existing workspace by slug should return it."""
        data = WorkspaceCreate(name="Find Me", slug="find-me")
        created = await create_workspace(db_session, data, cache=fake_redis)
        await db_session.commit()

        found = await get_workspace_by_slug(
            db_session, "find-me", cache=fake_redis
        )

        assert found.id == created.id
        assert found.slug == "find-me"

    async def test_get_nonexistent_workspace_raises(
        self,
        db_session: AsyncSession,
    ):
        """Getting a workspace that does not exist should raise NotFoundError."""
        with pytest.raises(WorkspaceNotFoundError) as exc_info:
            await get_workspace_by_slug(db_session, "does-not-exist")
        assert "does-not-exist" in str(exc_info.value)

    async def test_get_inactive_workspace_raises(
        self,
        db_session: AsyncSession,
        fake_redis,
    ):
        """
        Getting a soft-deleted workspace should raise NotFoundError.

        SKILL: Testing soft delete behavior
        """
        data = WorkspaceCreate(name="Will Delete", slug="will-delete")
        await create_workspace(db_session, data, cache=fake_redis)
        await db_session.commit()

        # Soft delete it
        await deactivate_workspace(db_session, "will-delete", cache=fake_redis)
        await db_session.commit()

        # Now it should not be found (active_only=True by default)
        with pytest.raises(WorkspaceNotFoundError):
            await get_workspace_by_slug(db_session, "will-delete")


class TestUpdateWorkspace:
    """Tests for update_workspace service function."""

    async def test_update_workspace_name(
        self,
        db_session: AsyncSession,
        fake_redis,
    ):
        """Updating workspace name should change only the name."""
        await create_workspace(
            db_session,
            WorkspaceCreate(name="Old Name", slug="update-me"),
            cache=fake_redis,
        )
        await db_session.commit()

        updated = await update_workspace(
            db_session,
            "update-me",
            WorkspaceUpdate(name="New Name"),
            cache=fake_redis,
        )

        assert updated.name == "New Name"
        assert updated.slug == "update-me"  # unchanged

    async def test_update_nonexistent_workspace_raises(
        self,
        db_session: AsyncSession,
    ):
        """Updating a workspace that does not exist should raise NotFoundError."""
        with pytest.raises(WorkspaceNotFoundError):
            await update_workspace(
                db_session,
                "ghost-workspace",
                WorkspaceUpdate(name="New Name"),
            )


class TestDeactivateWorkspace:
    """Tests for deactivate_workspace service function."""

    async def test_deactivate_workspace(
        self,
        db_session: AsyncSession,
        fake_redis,
    ):
        """Deactivating a workspace should set is_active to False."""
        await create_workspace(
            db_session,
            WorkspaceCreate(name="Active Now", slug="active-now"),
            cache=fake_redis,
        )
        await db_session.commit()

        deactivated = await deactivate_workspace(
            db_session, "active-now", cache=fake_redis
        )

        assert deactivated.is_active is False

    async def test_deactivate_nonexistent_raises(
        self,
        db_session: AsyncSession,
    ):
        """Deactivating a workspace that does not exist should raise NotFoundError."""
        with pytest.raises(WorkspaceNotFoundError):
            await deactivate_workspace(db_session, "ghost")