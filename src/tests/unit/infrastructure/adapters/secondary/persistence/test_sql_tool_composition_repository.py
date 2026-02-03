"""
Tests for V2 SqlToolCompositionRepository using BaseRepository.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.sql_tool_composition_repository import (
    SqlToolCompositionRepository,
)


@pytest.fixture
async def v2_composition_repo(v2_db_session: AsyncSession) -> SqlToolCompositionRepository:
    """Create a V2 tool composition repository for testing."""
    return SqlToolCompositionRepository(v2_db_session)


class TestSqlToolCompositionRepositoryCreate:
    """Tests for creating tool compositions."""

    @pytest.mark.asyncio
    async def test_save_new_composition(self, v2_composition_repo: SqlToolCompositionRepository):
        """Test saving a new tool composition."""
        from src.domain.model.agent import ToolComposition

        composition = ToolComposition(
            id="comp-test-1",
            tenant_id="tenant-1",
            name="test_composition",
            description="Test composition",
            project_id=None,
            tools=["search", "calculate"],
            execution_template={"test": "template"},
            success_count=0,
            failure_count=0,
            usage_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        result = await v2_composition_repo.save(composition)

        assert result.id == "comp-test-1"
        assert result.name == "test_composition"

    @pytest.mark.asyncio
    async def test_save_updates_existing(self, v2_composition_repo: SqlToolCompositionRepository):
        """Test saving updates an existing composition."""
        from src.domain.model.agent import ToolComposition

        composition = ToolComposition(
            id="comp-update-1",
            tenant_id="tenant-1",
            name="update_composition",
            description="Original",
            project_id=None,
            tools=["tool1"],
            execution_template={},
            success_count=0,
            failure_count=0,
            usage_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_composition_repo.save(composition)

        composition.description = "Updated"
        composition.tools = ["tool1", "tool2"]

        result = await v2_composition_repo.save(composition)
        assert result.description == "Updated"
        assert len(result.tools) == 2


class TestSqlToolCompositionRepositoryFind:
    """Tests for finding compositions."""

    @pytest.mark.asyncio
    async def test_get_by_id_existing(self, v2_composition_repo: SqlToolCompositionRepository):
        """Test getting a composition by ID."""
        from src.domain.model.agent import ToolComposition

        composition = ToolComposition(
            id="comp-find-1",
            tenant_id="tenant-1",
            name="find_composition",
            description="Find me",
            project_id=None,
            tools=["test_tool"],
            execution_template={},
            success_count=5,
            failure_count=2,
            usage_count=7,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_composition_repo.save(composition)

        result = await v2_composition_repo.get_by_id("comp-find-1")
        assert result is not None
        assert result.name == "find_composition"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, v2_composition_repo: SqlToolCompositionRepository):
        """Test getting a non-existent composition returns None."""
        result = await v2_composition_repo.get_by_id("non-existent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_name(self, v2_composition_repo: SqlToolCompositionRepository):
        """Test getting a composition by name."""
        from src.domain.model.agent import ToolComposition

        composition = ToolComposition(
            id="comp-name-1",
            tenant_id="tenant-1",
            name="unique_name",
            description="Unique",
            project_id=None,
            tools=["test_tool"],
            execution_template={},
            success_count=0,
            failure_count=0,
            usage_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_composition_repo.save(composition)

        result = await v2_composition_repo.get_by_name("unique_name")
        assert result is not None
        assert result.id == "comp-name-1"

    @pytest.mark.asyncio
    async def test_list_by_tools(self, v2_composition_repo: SqlToolCompositionRepository):
        """Test listing compositions that use specific tools."""
        from src.domain.model.agent import ToolComposition

        comp1 = ToolComposition(
            id="comp-tools-1",
            tenant_id="tenant-1",
            name="comp1",
            description="Uses search",
            project_id=None,
            tools=["search", "calculate"],
            execution_template={},
            success_count=0,
            failure_count=0,
            usage_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        comp2 = ToolComposition(
            id="comp-tools-2",
            tenant_id="tenant-1",
            name="comp2",
            description="Uses calculate",
            project_id=None,
            tools=["calculate"],
            execution_template={},
            success_count=0,
            failure_count=0,
            usage_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        comp3 = ToolComposition(
            id="comp-tools-3",
            tenant_id="tenant-1",
            name="comp3",
            description="Uses other",
            project_id=None,
            tools=["other"],
            execution_template={},
            success_count=0,
            failure_count=0,
            usage_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_composition_repo.save(comp1)
        await v2_composition_repo.save(comp2)
        await v2_composition_repo.save(comp3)

        # Get compositions that use "search"
        results = await v2_composition_repo.list_by_tools(["search"])
        assert len(results) == 1
        assert results[0].name == "comp1"

        # Get compositions that use "calculate"
        results = await v2_composition_repo.list_by_tools(["calculate"])
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_list_all(self, v2_composition_repo: SqlToolCompositionRepository):
        """Test listing all compositions."""
        from src.domain.model.agent import ToolComposition

        for i in range(3):
            composition = ToolComposition(
                id=f"comp-list-{i}",
                tenant_id="tenant-1",
                name=f"list-{i}",
                description=f"List {i}",
                project_id=None,
                tools=[f"tool-{i}"],
                execution_template={},
                success_count=i,
                failure_count=0,
                usage_count=i * 10,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await v2_composition_repo.save(composition)

        results = await v2_composition_repo.list_all()
        assert len(results) == 3
        # Should be ordered by usage_count desc
        assert results[0].usage_count >= results[1].usage_count


class TestSqlToolCompositionRepositoryUpdateUsage:
    """Tests for updating usage statistics."""

    @pytest.mark.asyncio
    async def test_update_usage_success(self, v2_composition_repo: SqlToolCompositionRepository):
        """Test updating usage with success."""
        from src.domain.model.agent import ToolComposition

        composition = ToolComposition(
            id="comp-usage-1",
            tenant_id="tenant-1",
            name="usage_comp",
            description="Usage test",
            project_id=None,
            tools=["test_tool"],
            execution_template={},
            success_count=5,
            failure_count=2,
            usage_count=7,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_composition_repo.save(composition)

        result = await v2_composition_repo.update_usage("comp-usage-1", success=True)

        assert result.usage_count == 8
        assert result.success_count == 6

    @pytest.mark.asyncio
    async def test_update_usage_failure(self, v2_composition_repo: SqlToolCompositionRepository):
        """Test updating usage with failure."""
        from src.domain.model.agent import ToolComposition

        composition = ToolComposition(
            id="comp-usage-fail-1",
            tenant_id="tenant-1",
            name="usage_fail_comp",
            description="Usage fail test",
            project_id=None,
            tools=["test_tool"],
            execution_template={},
            success_count=5,
            failure_count=2,
            usage_count=7,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_composition_repo.save(composition)

        result = await v2_composition_repo.update_usage("comp-usage-fail-1", success=False)

        assert result.usage_count == 8
        assert result.failure_count == 3


class TestSqlToolCompositionRepositoryDelete:
    """Tests for deleting compositions."""

    @pytest.mark.asyncio
    async def test_delete_existing(self, v2_composition_repo: SqlToolCompositionRepository):
        """Test deleting an existing composition."""
        from src.domain.model.agent import ToolComposition

        composition = ToolComposition(
            id="comp-delete-1",
            tenant_id="tenant-1",
            name="delete_comp",
            description="Delete test",
            project_id=None,
            tools=["test_tool"],
            execution_template={},
            success_count=0,
            failure_count=0,
            usage_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_composition_repo.save(composition)

        result = await v2_composition_repo.delete("comp-delete-1")
        assert result is True

        retrieved = await v2_composition_repo.get_by_id("comp-delete-1")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, v2_composition_repo: SqlToolCompositionRepository):
        """Test deleting a non-existent composition returns False."""
        result = await v2_composition_repo.delete("non-existent")
        assert result is False
