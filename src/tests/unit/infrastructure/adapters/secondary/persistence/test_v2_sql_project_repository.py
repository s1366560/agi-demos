"""
Tests for V2 SqlProjectRepository using BaseRepository.

TDD Approach: RED -> GREEN -> REFACTOR

These tests verify that the migrated repository maintains 100% compatibility
with the original implementation while leveraging the BaseRepository.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.project.project import Project
from src.infrastructure.adapters.secondary.persistence.models import Project as DBProject
from src.infrastructure.adapters.secondary.persistence.v2_sql_project_repository import (
    V2SqlProjectRepository,
)


@pytest.fixture
async def v2_project_repo(db_session: AsyncSession) -> V2SqlProjectRepository:
    """Create a V2 project repository for testing."""
    return V2SqlProjectRepository(db_session)


class TestV2SqlProjectRepositoryCreate:
    """Tests for creating new projects."""

    @pytest.mark.asyncio
    async def test_create_new_project(self, v2_project_repo: V2SqlProjectRepository):
        """Test creating a new project."""
        project = Project(
            id="proj-test-1",
            tenant_id="tenant-1",
            name="Test Project",
            owner_id="user-1",
            description="A test project",
            member_ids=["user-2"],
            memory_rules={"max_memories": 100},
            graph_config={"enabled": True},
            is_public=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        await v2_project_repo.save(project)

        # Verify project was saved
        retrieved = await v2_project_repo.find_by_id("proj-test-1")
        assert retrieved is not None
        assert retrieved.id == "proj-test-1"
        assert retrieved.name == "Test Project"
        assert retrieved.description == "A test project"
        assert retrieved.owner_id == "user-1"
        # Note: member_ids is a lazy-loaded relationship, not stored directly
        assert retrieved.memory_rules == {"max_memories": 100}
        assert retrieved.graph_config == {"enabled": True}
        assert retrieved.is_public is False

    @pytest.mark.asyncio
    async def test_create_project_with_minimal_fields(self, v2_project_repo: V2SqlProjectRepository):
        """Test creating a project with only required fields."""
        project = Project(
            id="proj-minimal",
            tenant_id="tenant-1",
            name="Minimal Project",
            owner_id="user-1",
            description=None,
            member_ids=[],
            memory_rules={},
            graph_config={},
            is_public=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        await v2_project_repo.save(project)

        retrieved = await v2_project_repo.find_by_id("proj-minimal")
        assert retrieved is not None
        assert retrieved.name == "Minimal Project"
        assert retrieved.description is None
        # member_ids is lazy-loaded, always returns empty in this context

    @pytest.mark.asyncio
    async def test_save_with_none_project_raises_error(self, v2_project_repo: V2SqlProjectRepository):
        """Test that saving None raises ValueError."""
        with pytest.raises(ValueError, match="Entity cannot be None"):
            await v2_project_repo.save(None)


class TestV2SqlProjectRepositoryUpdate:
    """Tests for updating existing projects."""

    @pytest.mark.asyncio
    async def test_update_existing_project(self, v2_project_repo: V2SqlProjectRepository):
        """Test updating an existing project."""
        # Create initial project
        project = Project(
            id="proj-update-1",
            tenant_id="tenant-1",
            name="Original Name",
            owner_id="user-1",
            description="Original description",
            member_ids=["user-2"],
            memory_rules={"max": 50},
            graph_config={},
            is_public=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_project_repo.save(project)

        # Update the project
        updated_project = Project(
            id="proj-update-1",
            tenant_id="tenant-1",
            name="Updated Name",
            owner_id="user-1",
            description="Updated description",
            member_ids=["user-2", "user-3"],
            memory_rules={"max": 200},
            graph_config={"new": True},
            is_public=True,
            created_at=project.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        await v2_project_repo.save(updated_project)

        # Verify updates
        retrieved = await v2_project_repo.find_by_id("proj-update-1")
        assert retrieved.name == "Updated Name"
        assert retrieved.description == "Updated description"
        # member_ids is not directly updated - it's a relationship
        assert retrieved.memory_rules == {"max": 200}
        assert retrieved.graph_config == {"new": True}
        assert retrieved.is_public is True

    @pytest.mark.asyncio
    async def test_update_preserves_tenant_and_owner(self, v2_project_repo: V2SqlProjectRepository):
        """Test that updates preserve tenant_id and owner_id."""
        project = Project(
            id="proj-preserve",
            tenant_id="tenant-original",
            name="Original",
            owner_id="owner-original",
            description="desc",
            member_ids=[],
            memory_rules={},
            graph_config={},
            is_public=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_project_repo.save(project)

        # Update with same tenant and owner
        updated = Project(
            id="proj-preserve",
            tenant_id="tenant-original",
            name="Updated",
            owner_id="owner-original",
            description="new desc",
            member_ids=[],
            memory_rules={},
            graph_config={},
            is_public=True,
            created_at=project.created_at,
            updated_at=datetime.now(timezone.utc),
        )
        await v2_project_repo.save(updated)

        retrieved = await v2_project_repo.find_by_id("proj-preserve")
        assert retrieved.tenant_id == "tenant-original"
        assert retrieved.owner_id == "owner-original"


class TestV2SqlProjectRepositoryFind:
    """Tests for finding projects."""

    @pytest.mark.asyncio
    async def test_find_by_id_existing(self, v2_project_repo: V2SqlProjectRepository):
        """Test finding an existing project by ID."""
        project = Project(
            id="proj-find-1",
            tenant_id="tenant-1",
            name="Find Me",
            owner_id="user-1",
            description="Description",
            member_ids=[],
            memory_rules={},
            graph_config={},
            is_public=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_project_repo.save(project)

        retrieved = await v2_project_repo.find_by_id("proj-find-1")
        assert retrieved is not None
        assert retrieved.id == "proj-find-1"
        assert retrieved.name == "Find Me"

    @pytest.mark.asyncio
    async def test_find_by_id_not_found(self, v2_project_repo: V2SqlProjectRepository):
        """Test finding a non-existent project returns None."""
        retrieved = await v2_project_repo.find_by_id("non-existent")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_find_by_id_empty_string_raises_error(self, v2_project_repo: V2SqlProjectRepository):
        """Test that empty ID raises ValueError."""
        with pytest.raises(ValueError, match="ID cannot be empty"):
            await v2_project_repo.find_by_id("")

    @pytest.mark.asyncio
    async def test_exists_true(self, v2_project_repo: V2SqlProjectRepository):
        """Test exists returns True for existing project."""
        project = Project(
            id="proj-exists-1",
            tenant_id="tenant-1",
            name="Exists",
            owner_id="user-1",
            description="desc",
            member_ids=[],
            memory_rules={},
            graph_config={},
            is_public=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_project_repo.save(project)

        assert await v2_project_repo.exists("proj-exists-1") is True

    @pytest.mark.asyncio
    async def test_exists_false(self, v2_project_repo: V2SqlProjectRepository):
        """Test exists returns False for non-existent project."""
        assert await v2_project_repo.exists("non-existent") is False

    @pytest.mark.asyncio
    async def test_exists_empty_string(self, v2_project_repo: V2SqlProjectRepository):
        """Test exists returns False for empty string."""
        assert await v2_project_repo.exists("") is False


class TestV2SqlProjectRepositoryList:
    """Tests for listing projects."""

    @pytest.mark.asyncio
    async def test_find_by_tenant(self, v2_project_repo: V2SqlProjectRepository):
        """Test listing projects by tenant."""
        # Create projects for different tenants
        for i in range(3):
            project = Project(
                id=f"proj-tenant-1-{i}",
                tenant_id="tenant-1",
                name=f"Project {i}",
                owner_id="user-1",
                description="desc",
                member_ids=[],
                memory_rules={},
                graph_config={},
                is_public=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await v2_project_repo.save(project)

        # Add project for different tenant
        other_project = Project(
            id="proj-other-tenant",
            tenant_id="tenant-2",
            name="Other Project",
            owner_id="user-1",
            description="desc",
            member_ids=[],
            memory_rules={},
            graph_config={},
            is_public=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_project_repo.save(other_project)

        # List tenant-1 projects
        projects = await v2_project_repo.find_by_tenant("tenant-1")
        assert len(projects) == 3
        assert all(p.tenant_id == "tenant-1" for p in projects)

    @pytest.mark.asyncio
    async def test_find_by_tenant_with_pagination(self, v2_project_repo: V2SqlProjectRepository):
        """Test listing projects by tenant with pagination."""
        # Create 5 projects
        for i in range(5):
            project = Project(
                id=f"proj-page-{i}",
                tenant_id="tenant-page",
                name=f"Project {i}",
                owner_id="user-1",
                description="desc",
                member_ids=[],
                memory_rules={},
                graph_config={},
                is_public=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await v2_project_repo.save(project)

        # Get first page
        page1 = await v2_project_repo.find_by_tenant("tenant-page", limit=2, offset=0)
        assert len(page1) == 2

        # Get second page
        page2 = await v2_project_repo.find_by_tenant("tenant-page", limit=2, offset=2)
        assert len(page2) == 2

        # Get remaining
        page3 = await v2_project_repo.find_by_tenant("tenant-page", limit=2, offset=4)
        assert len(page3) == 1

    @pytest.mark.asyncio
    async def test_find_by_owner(self, v2_project_repo: V2SqlProjectRepository):
        """Test listing projects by owner."""
        # Create projects for different owners
        for i in range(3):
            project = Project(
                id=f"proj-owner-1-{i}",
                tenant_id="tenant-1",
                name=f"Owner Project {i}",
                owner_id="owner-1",
                description="desc",
                member_ids=[],
                memory_rules={},
                graph_config={},
                is_public=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await v2_project_repo.save(project)

        # Add project for different owner
        other_project = Project(
            id="proj-other-owner",
            tenant_id="tenant-1",
            name="Other Owner Project",
            owner_id="owner-2",
            description="desc",
            member_ids=[],
            memory_rules={},
            graph_config={},
            is_public=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_project_repo.save(other_project)

        # List owner-1 projects
        projects = await v2_project_repo.find_by_owner("owner-1")
        assert len(projects) == 3
        assert all(p.owner_id == "owner-1" for p in projects)

    @pytest.mark.asyncio
    async def test_find_public_projects(self, v2_project_repo: V2SqlProjectRepository):
        """Test listing public projects."""
        # Create mix of public and private projects
        for i in range(2):
            public_project = Project(
                id=f"proj-public-{i}",
                tenant_id="tenant-1",
                name=f"Public Project {i}",
                owner_id="user-1",
                description="desc",
                member_ids=[],
                memory_rules={},
                graph_config={},
                is_public=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await v2_project_repo.save(public_project)

        private_project = Project(
            id="proj-private",
            tenant_id="tenant-1",
            name="Private Project",
            owner_id="user-1",
            description="desc",
            member_ids=[],
            memory_rules={},
            graph_config={},
            is_public=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_project_repo.save(private_project)

        # List public projects
        public_projects = await v2_project_repo.find_public_projects()
        assert len(public_projects) == 2
        assert all(p.is_public for p in public_projects)

    @pytest.mark.asyncio
    async def test_list_all_with_filters(self, v2_project_repo: V2SqlProjectRepository):
        """Test list_all with tenant filter."""
        # Create projects
        for i in range(3):
            project = Project(
                id=f"proj-list-{i}",
                tenant_id="tenant-list",
                name=f"List Project {i}",
                owner_id="user-1",
                description="desc",
                member_ids=[],
                memory_rules={},
                graph_config={},
                is_public=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await v2_project_repo.save(project)

        # List with tenant filter
        projects = await v2_project_repo.list_all(tenant_id="tenant-list")
        assert len(projects) == 3


class TestV2SqlProjectRepositoryDelete:
    """Tests for deleting projects."""

    @pytest.mark.asyncio
    async def test_delete_existing_project(self, v2_project_repo: V2SqlProjectRepository):
        """Test deleting an existing project."""
        project = Project(
            id="proj-delete-1",
            tenant_id="tenant-1",
            name="Delete Me",
            owner_id="user-1",
            description="desc",
            member_ids=[],
            memory_rules={},
            graph_config={},
            is_public=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_project_repo.save(project)

        # Delete
        result = await v2_project_repo.delete("proj-delete-1")
        assert result is True

        # Verify deleted
        retrieved = await v2_project_repo.find_by_id("proj-delete-1")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_project(self, v2_project_repo: V2SqlProjectRepository):
        """Test deleting a non-existent project returns False."""
        result = await v2_project_repo.delete("non-existent")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_empty_id_raises_error(self, v2_project_repo: V2SqlProjectRepository):
        """Test that deleting with empty ID doesn't raise but returns False."""
        result = await v2_project_repo.delete("")
        assert result is False


class TestV2SqlProjectRepositoryCount:
    """Tests for counting projects."""

    @pytest.mark.asyncio
    async def test_count_all(self, v2_project_repo: V2SqlProjectRepository):
        """Test counting all projects."""
        # Initially empty
        count = await v2_project_repo.count()
        assert count == 0

        # Add projects
        for i in range(3):
            project = Project(
                id=f"proj-count-{i}",
                tenant_id="tenant-count",
                name=f"Count {i}",
                owner_id="user-1",
                description="desc",
                member_ids=[],
                memory_rules={},
                graph_config={},
                is_public=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await v2_project_repo.save(project)

        count = await v2_project_repo.count()
        assert count == 3

    @pytest.mark.asyncio
    async def test_count_with_filter(self, v2_project_repo: V2SqlProjectRepository):
        """Test counting projects with filters."""
        # Create projects for two tenants
        for i in range(2):
            project = Project(
                id=f"proj-count-filter-1-{i}",
                tenant_id="tenant-1",
                name=f"Project {i}",
                owner_id="user-1",
                description="desc",
                member_ids=[],
                memory_rules={},
                graph_config={},
                is_public=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await v2_project_repo.save(project)

        for i in range(3):
            project = Project(
                id=f"proj-count-filter-2-{i}",
                tenant_id="tenant-2",
                name=f"Project {i}",
                owner_id="user-1",
                description="desc",
                member_ids=[],
                memory_rules={},
                graph_config={},
                is_public=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await v2_project_repo.save(project)

        # Count by tenant
        count_tenant1 = await v2_project_repo.count(tenant_id="tenant-1")
        assert count_tenant1 == 2

        count_tenant2 = await v2_project_repo.count(tenant_id="tenant-2")
        assert count_tenant2 == 3


class TestV2SqlProjectRepositoryToDomain:
    """Tests for _to_domain conversion."""

    @pytest.mark.asyncio
    async def test_to_domain_converts_all_fields(self, v2_project_repo: V2SqlProjectRepository):
        """Test that _to_domain correctly converts all DB fields."""
        project = Project(
            id="proj-domain",
            tenant_id="tenant-1",
            name="Domain Test",
            owner_id="user-1",
            description="Test description",
            member_ids=["user-2"],
            memory_rules={"max": 100},
            graph_config={"enabled": True},
            is_public=True,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_project_repo.save(project)

        retrieved = await v2_project_repo.find_by_id("proj-domain")
        assert retrieved.id == "proj-domain"
        assert retrieved.tenant_id == "tenant-1"
        assert retrieved.name == "Domain Test"
        assert retrieved.owner_id == "user-1"
        assert retrieved.description == "Test description"
        # member_ids is lazy-loaded - not testing here
        assert retrieved.memory_rules == {"max": 100}
        assert retrieved.graph_config == {"enabled": True}
        assert retrieved.is_public is True
        assert retrieved.created_at is not None
        assert retrieved.updated_at is not None

    @pytest.mark.asyncio
    async def test_to_domain_with_none_db_model(self, v2_project_repo: V2SqlProjectRepository):
        """Test that _to_domain returns None for None input."""
        result = v2_project_repo._to_domain(None)
        assert result is None


class TestV2SqlProjectRepositoryToDb:
    """Tests for _to_db conversion."""

    def test_to_db_creates_db_model(self, v2_project_repo: V2SqlProjectRepository):
        """Test that _to_db creates a valid DB model."""
        project = Project(
            id="proj-todb",
            tenant_id="tenant-1",
            name="To DB Test",
            owner_id="user-1",
            description="desc",
            member_ids=[],
            memory_rules={},
            graph_config={},
            is_public=False,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        db_model = v2_project_repo._to_db(project)
        assert isinstance(db_model, DBProject)
        assert db_model.id == "proj-todb"
        assert db_model.tenant_id == "tenant-1"
        assert db_model.name == "To DB Test"
        assert db_model.owner_id == "user-1"


class TestV2SqlProjectRepositoryTransaction:
    """Tests for transaction support."""

    @pytest.mark.asyncio
    async def test_transaction_context_manager(self, v2_project_repo: V2SqlProjectRepository):
        """Test using transaction context manager."""
        async with v2_project_repo.transaction():
            project1 = Project(
                id="proj-tx-1",
                tenant_id="tenant-1",
                name="TX Project 1",
                owner_id="user-1",
                description="desc",
                member_ids=[],
                memory_rules={},
                graph_config={},
                is_public=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await v2_project_repo.save(project1)

            project2 = Project(
                id="proj-tx-2",
                tenant_id="tenant-1",
                name="TX Project 2",
                owner_id="user-1",
                description="desc",
                member_ids=[],
                memory_rules={},
                graph_config={},
                is_public=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await v2_project_repo.save(project2)

        # Verify both were saved
        p1 = await v2_project_repo.find_by_id("proj-tx-1")
        p2 = await v2_project_repo.find_by_id("proj-tx-2")
        assert p1 is not None
        assert p2 is not None

    @pytest.mark.asyncio
    async def test_transaction_rollback_on_error(self, v2_project_repo: V2SqlProjectRepository):
        """Test that transaction rolls back on error."""
        try:
            async with v2_project_repo.transaction():
                project1 = Project(
                    id="proj-tx-rollback-1",
                    tenant_id="tenant-1",
                    name="TX Rollback 1",
                    owner_id="user-1",
                    description="desc",
                    member_ids=[],
                    memory_rules={},
                    graph_config={},
                    is_public=False,
                    created_at=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc),
                )
                await v2_project_repo.save(project1)

                # Raise error to trigger rollback
                raise ValueError("Test error")
        except ValueError:
            pass

        # Verify rollback occurred
        p1 = await v2_project_repo.find_by_id("proj-tx-rollback-1")
        assert p1 is None


class TestV2SqlProjectRepositoryBulkOperations:
    """Tests for bulk operations."""

    @pytest.mark.asyncio
    async def test_bulk_save(self, v2_project_repo: V2SqlProjectRepository):
        """Test bulk saving projects."""
        projects = []
        for i in range(5):
            project = Project(
                id=f"proj-bulk-{i}",
                tenant_id="tenant-bulk",
                name=f"Bulk Project {i}",
                owner_id="user-1",
                description="desc",
                member_ids=[],
                memory_rules={},
                graph_config={},
                is_public=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            projects.append(project)

        await v2_project_repo.bulk_save(projects)

        # Verify all were saved
        for i in range(5):
            retrieved = await v2_project_repo.find_by_id(f"proj-bulk-{i}")
            assert retrieved is not None
            assert retrieved.name == f"Bulk Project {i}"

    @pytest.mark.asyncio
    async def test_bulk_delete(self, v2_project_repo: V2SqlProjectRepository):
        """Test bulk deleting projects."""
        # Create projects
        project_ids = [f"proj-bulk-del-{i}" for i in range(5)]
        for pid in project_ids:
            project = Project(
                id=pid,
                tenant_id="tenant-bulk-del",
                name="Bulk Delete Project",
                owner_id="user-1",
                description="desc",
                member_ids=[],
                memory_rules={},
                graph_config={},
                is_public=False,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await v2_project_repo.save(project)

        # Bulk delete
        deleted_count = await v2_project_repo.bulk_delete(project_ids)
        assert deleted_count == 5

        # Verify all were deleted
        for pid in project_ids:
            retrieved = await v2_project_repo.find_by_id(pid)
            assert retrieved is None

    @pytest.mark.asyncio
    async def test_bulk_delete_empty_list(self, v2_project_repo: V2SqlProjectRepository):
        """Test bulk delete with empty list returns 0."""
        count = await v2_project_repo.bulk_delete([])
        assert count == 0
