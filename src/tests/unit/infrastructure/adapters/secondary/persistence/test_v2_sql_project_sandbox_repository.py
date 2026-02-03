"""
Tests for V2 SqlProjectSandboxRepository using BaseRepository.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.sandbox.project_sandbox import (
    ProjectSandbox,
    ProjectSandboxStatus,
)
from src.infrastructure.adapters.secondary.persistence.v2_sql_project_sandbox_repository import (
    V2SqlProjectSandboxRepository,
)


@pytest.fixture
async def v2_sandbox_repo(v2_db_session: AsyncSession) -> V2SqlProjectSandboxRepository:
    """Create a V2 project sandbox repository for testing."""
    return V2SqlProjectSandboxRepository(v2_db_session)


def make_sandbox(
    sandbox_id: str,
    project_id: str,
    status: ProjectSandboxStatus = ProjectSandboxStatus.RUNNING,
) -> ProjectSandbox:
    """Factory for creating ProjectSandbox objects."""
    return ProjectSandbox(
        id=sandbox_id,
        project_id=project_id,
        tenant_id="tenant-1",
        sandbox_id=f"sandbox-{project_id}",
        status=status,
        created_at=datetime.now(timezone.utc),
        started_at=datetime.now(timezone.utc),
        last_accessed_at=datetime.now(timezone.utc),
        health_checked_at=datetime.now(timezone.utc),
        error_message=None,
        metadata={},
    )


class TestV2SqlProjectSandboxRepositoryCreate:
    """Tests for creating sandbox associations."""

    @pytest.mark.asyncio
    async def test_save_new_sandbox(self, v2_sandbox_repo: V2SqlProjectSandboxRepository):
        """Test saving a new sandbox association."""
        sandbox = make_sandbox("sb-1", "project-1")

        await v2_sandbox_repo.save(sandbox)

        result = await v2_sandbox_repo.find_by_id("sb-1")
        assert result is not None
        assert result.project_id == "project-1"

    @pytest.mark.asyncio
    async def test_save_updates_existing(self, v2_sandbox_repo: V2SqlProjectSandboxRepository):
        """Test saving updates an existing association."""
        sandbox = make_sandbox("sb-update-1", "project-1")
        await v2_sandbox_repo.save(sandbox)

        sandbox.status = ProjectSandboxStatus.STOPPED
        sandbox.error_message = "Test error"

        await v2_sandbox_repo.save(sandbox)

        result = await v2_sandbox_repo.find_by_id("sb-update-1")
        assert result.status == ProjectSandboxStatus.STOPPED
        assert result.error_message == "Test error"


class TestV2SqlProjectSandboxRepositoryFind:
    """Tests for finding sandbox associations."""

    @pytest.mark.asyncio
    async def test_find_by_id_existing(self, v2_sandbox_repo: V2SqlProjectSandboxRepository):
        """Test finding a sandbox by ID."""
        sandbox = make_sandbox("sb-find-1", "project-1")
        await v2_sandbox_repo.save(sandbox)

        result = await v2_sandbox_repo.find_by_id("sb-find-1")
        assert result is not None
        assert result.project_id == "project-1"

    @pytest.mark.asyncio
    async def test_find_by_id_not_found(self, v2_sandbox_repo: V2SqlProjectSandboxRepository):
        """Test finding a non-existent sandbox returns None."""
        result = await v2_sandbox_repo.find_by_id("non-existent")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_by_project(self, v2_sandbox_repo: V2SqlProjectSandboxRepository):
        """Test finding sandbox by project ID."""
        sandbox = make_sandbox("sb-proj-1", "project-find-1")
        await v2_sandbox_repo.save(sandbox)

        result = await v2_sandbox_repo.find_by_project("project-find-1")
        assert result is not None
        assert result.id == "sb-proj-1"

    @pytest.mark.asyncio
    async def test_find_by_sandbox(self, v2_sandbox_repo: V2SqlProjectSandboxRepository):
        """Test finding sandbox by sandbox ID."""
        sandbox = make_sandbox("sb-sand-1", "project-1")
        await v2_sandbox_repo.save(sandbox)

        result = await v2_sandbox_repo.find_by_sandbox("sandbox-project-1")
        assert result is not None
        assert result.project_id == "project-1"

    @pytest.mark.asyncio
    async def test_find_by_tenant(self, v2_sandbox_repo: V2SqlProjectSandboxRepository):
        """Test listing sandboxes by tenant."""
        for i in range(3):
            sandbox = make_sandbox(f"sb-tenant-{i}", f"project-{i}")
            await v2_sandbox_repo.save(sandbox)

        results = await v2_sandbox_repo.find_by_tenant("tenant-1")
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_find_by_tenant_with_status(self, v2_sandbox_repo: V2SqlProjectSandboxRepository):
        """Test listing sandboxes by tenant and status."""
        sb1 = make_sandbox("sb-status-1", "project-1", ProjectSandboxStatus.RUNNING)
        sb2 = make_sandbox("sb-status-2", "project-2", ProjectSandboxStatus.STOPPED)
        await v2_sandbox_repo.save(sb1)
        await v2_sandbox_repo.save(sb2)

        results = await v2_sandbox_repo.find_by_tenant("tenant-1", ProjectSandboxStatus.RUNNING)
        assert len(results) == 1
        assert results[0].status == ProjectSandboxStatus.RUNNING

    @pytest.mark.asyncio
    async def test_find_by_status(self, v2_sandbox_repo: V2SqlProjectSandboxRepository):
        """Test finding sandboxes by status."""
        sb1 = make_sandbox("sb-fs-1", "project-1", ProjectSandboxStatus.RUNNING)
        sb2 = make_sandbox("sb-fs-2", "project-2", ProjectSandboxStatus.RUNNING)
        sb3 = make_sandbox("sb-fs-3", "project-3", ProjectSandboxStatus.STOPPED)
        await v2_sandbox_repo.save(sb1)
        await v2_sandbox_repo.save(sb2)
        await v2_sandbox_repo.save(sb3)

        results = await v2_sandbox_repo.find_by_status(ProjectSandboxStatus.RUNNING)
        assert len(results) == 2


class TestV2SqlProjectSandboxRepositoryDelete:
    """Tests for deleting sandbox associations."""

    @pytest.mark.asyncio
    async def test_delete_existing(self, v2_sandbox_repo: V2SqlProjectSandboxRepository):
        """Test deleting an existing sandbox."""
        sandbox = make_sandbox("sb-delete-1", "project-1")
        await v2_sandbox_repo.save(sandbox)

        result = await v2_sandbox_repo.delete("sb-delete-1")
        assert result is True

        retrieved = await v2_sandbox_repo.find_by_id("sb-delete-1")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, v2_sandbox_repo: V2SqlProjectSandboxRepository):
        """Test deleting a non-existent sandbox returns False."""
        result = await v2_sandbox_repo.delete("non-existent")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_by_project(self, v2_sandbox_repo: V2SqlProjectSandboxRepository):
        """Test deleting sandbox by project."""
        sandbox = make_sandbox("sb-del-proj-1", "project-del-1")
        await v2_sandbox_repo.save(sandbox)

        result = await v2_sandbox_repo.delete_by_project("project-del-1")
        assert result is True

        retrieved = await v2_sandbox_repo.find_by_project("project-del-1")
        assert retrieved is None


class TestV2SqlProjectSandboxRepositoryUtility:
    """Tests for utility methods."""

    @pytest.mark.asyncio
    async def test_exists_for_project(self, v2_sandbox_repo: V2SqlProjectSandboxRepository):
        """Test checking if sandbox exists for project."""
        sandbox = make_sandbox("sb-exists-1", "project-exists-1")
        await v2_sandbox_repo.save(sandbox)

        assert await v2_sandbox_repo.exists_for_project("project-exists-1") is True
        assert await v2_sandbox_repo.exists_for_project("non-existent") is False

    @pytest.mark.asyncio
    async def test_count_by_tenant(self, v2_sandbox_repo: V2SqlProjectSandboxRepository):
        """Test counting sandboxes by tenant."""
        for i in range(3):
            sandbox = make_sandbox(f"sb-count-{i}", f"project-count-{i}")
            await v2_sandbox_repo.save(sandbox)

        count = await v2_sandbox_repo.count_by_tenant("tenant-1")
        assert count == 3

    @pytest.mark.asyncio
    async def test_count_by_tenant_with_status(self, v2_sandbox_repo: V2SqlProjectSandboxRepository):
        """Test counting sandboxes by tenant and status."""
        sb1 = make_sandbox("sb-cs-1", "project-1", ProjectSandboxStatus.RUNNING)
        sb2 = make_sandbox("sb-cs-2", "project-2", ProjectSandboxStatus.STOPPED)
        await v2_sandbox_repo.save(sb1)
        await v2_sandbox_repo.save(sb2)

        count = await v2_sandbox_repo.count_by_tenant("tenant-1", ProjectSandboxStatus.RUNNING)
        assert count == 1


class TestV2SqlProjectSandboxRepositoryStale:
    """Tests for finding stale sandboxes."""

    @pytest.mark.asyncio
    async def test_find_stale(self, v2_sandbox_repo: V2SqlProjectSandboxRepository):
        """Test finding stale sandboxes."""
        # Create a sandbox with old last_accessed_at
        old_time = datetime.now(timezone.utc) - timedelta(seconds=100)
        stale_sandbox = make_sandbox("sb-stale-1", "project-stale-1")
        stale_sandbox.last_accessed_at = old_time
        await v2_sandbox_repo.save(stale_sandbox)

        # Create a fresh sandbox
        fresh_sandbox = make_sandbox("sb-fresh-1", "project-fresh-1")
        await v2_sandbox_repo.save(fresh_sandbox)

        results = await v2_sandbox_repo.find_stale(max_idle_seconds=60)
        assert len(results) >= 1
        # The stale sandbox should be in the results
        stale_ids = [r.id for r in results]
        assert "sb-stale-1" in stale_ids
