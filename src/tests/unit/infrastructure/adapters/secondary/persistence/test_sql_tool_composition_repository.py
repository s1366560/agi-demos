"""
Unit tests for SQLToolCompositionRepository (T105)

Tests the SQL implementation of ToolComposition repository.

TDD: Tests written first, repository will be implemented to make these pass.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import ToolComposition
from src.infrastructure.adapters.secondary.persistence.sql_tool_composition_repository import (
    SQLToolCompositionRepository,
)


@pytest.mark.asyncio
class TestSQLToolCompositionRepository:
    """Tests for SQLToolCompositionRepository."""

    async def test_save_new_composition(self, test_db: AsyncSession):
        """Test saving a new tool composition."""
        repo = SQLToolCompositionRepository(test_db)

        composition = ToolComposition.create(
            name="Search and Summarize",
            description="Search memories and summarize results",
            tools=["memory_search", "summary"],
            composition_type="sequential",
        )

        saved = await repo.save(composition)

        assert saved.id == composition.id
        assert saved.name == "Search and Summarize"
        assert saved.description == "Search memories and summarize results"
        assert saved.tools == ["memory_search", "summary"]
        assert saved.success_rate == 1.0

    async def test_save_updates_existing_composition(self, test_db: AsyncSession):
        """Test saving updates an existing composition."""
        repo = SQLToolCompositionRepository(test_db)

        # Create initial composition
        composition = ToolComposition.create(
            name="Update Test",
            description="Initial description",
            tools=["tool1"],
        )

        saved = await repo.save(composition)
        assert saved.success_count == 0

        # Update composition
        updated = saved.record_usage(success=True)
        final = await repo.save(updated)

        assert final.id == composition.id
        assert final.success_count == 1
        assert final.usage_count == 1

    async def test_get_by_id(self, test_db: AsyncSession):
        """Test retrieving a composition by ID."""
        repo = SQLToolCompositionRepository(test_db)

        composition = ToolComposition.create(
            name="Get Test",
            description="Test get by id",
            tools=["tool1"],
        )

        await repo.save(composition)
        retrieved = await repo.get_by_id(composition.id)

        assert retrieved is not None
        assert retrieved.id == composition.id
        assert retrieved.name == "Get Test"

    async def test_get_by_id_returns_none_for_not_found(self, test_db: AsyncSession):
        """Test that get_by_id returns None for non-existent composition."""
        repo = SQLToolCompositionRepository(test_db)

        retrieved = await repo.get_by_id("non-existent-id")

        assert retrieved is None

    async def test_get_by_name(self, test_db: AsyncSession):
        """Test retrieving a composition by name."""
        repo = SQLToolCompositionRepository(test_db)

        composition = ToolComposition.create(
            name="Unique Name",
            description="Test get by name",
            tools=["tool1"],
        )

        await repo.save(composition)
        retrieved = await repo.get_by_name("Unique Name")

        assert retrieved is not None
        assert retrieved.id == composition.id
        assert retrieved.name == "Unique Name"

    async def test_get_by_name_returns_none_for_not_found(self, test_db: AsyncSession):
        """Test that get_by_name returns None for non-existent composition."""
        repo = SQLToolCompositionRepository(test_db)

        retrieved = await repo.get_by_name("non-existent-name")

        assert retrieved is None

    async def test_list_by_tools(self, test_db: AsyncSession):
        """Test listing compositions that use specific tools."""
        repo = SQLToolCompositionRepository(test_db)

        # Create compositions with different tools
        comp1 = ToolComposition.create(
            name="Comp 1",
            description="Uses memory_search",
            tools=["memory_search", "summary"],
        )

        comp2 = ToolComposition.create(
            name="Comp 2",
            description="Uses entity_lookup",
            tools=["entity_lookup"],
        )

        comp3 = ToolComposition.create(
            name="Comp 3",
            description="Also uses memory_search",
            tools=["memory_search", "analysis"],
        )

        await repo.save(comp1)
        await repo.save(comp2)
        await repo.save(comp3)

        # List compositions using memory_search
        results = await repo.list_by_tools(["memory_search"])

        assert len(results) >= 2
        composition_ids = [c.id for c in results]
        assert comp1.id in composition_ids
        assert comp3.id in composition_ids

    async def test_list_all(self, test_db: AsyncSession):
        """Test listing all compositions."""
        repo = SQLToolCompositionRepository(test_db)

        # Create multiple compositions
        comp1 = ToolComposition.create(
            name="List Test 1",
            description="First composition",
            tools=["tool1"],
        )

        comp2 = ToolComposition.create(
            name="List Test 2",
            description="Second composition",
            tools=["tool2"],
        )

        await repo.save(comp1)
        await repo.save(comp2)

        # List all
        results = await repo.list_all(limit=10)

        assert len(results) >= 2
        composition_names = [c.name for c in results]
        assert "List Test 1" in composition_names
        assert "List Test 2" in composition_names

    async def test_list_all_respects_limit(self, test_db: AsyncSession):
        """Test that list_all respects the limit parameter."""
        repo = SQLToolCompositionRepository(test_db)

        # Create 3 compositions
        for i in range(3):
            comp = ToolComposition.create(
                name=f"Limit Test {i}",
                description=f"Composition {i}",
                tools=["tool1"],
            )
            await repo.save(comp)

        # List with limit of 2
        results = await repo.list_all(limit=2)

        assert len(results) <= 2

    async def test_update_usage_success(self, test_db: AsyncSession):
        """Test updating usage with success."""
        repo = SQLToolCompositionRepository(test_db)

        composition = ToolComposition.create(
            name="Usage Test",
            description="Test usage tracking",
            tools=["tool1"],
        )

        saved = await repo.save(composition)
        assert saved.success_count == 0
        assert saved.usage_count == 0

        # Record successful usage
        updated = await repo.update_usage(composition.id, success=True)

        assert updated is not None
        assert updated.success_count == 1
        assert updated.failure_count == 0
        assert updated.usage_count == 1
        assert updated.success_rate == 1.0

    async def test_update_usage_failure(self, test_db: AsyncSession):
        """Test updating usage with failure."""
        repo = SQLToolCompositionRepository(test_db)

        composition = ToolComposition.create(
            name="Failure Test",
            description="Test failure tracking",
            tools=["tool1"],
        )

        await repo.save(composition)

        # Record failed usage
        updated = await repo.update_usage(composition.id, success=False)

        assert updated is not None
        assert updated.success_count == 0
        assert updated.failure_count == 1
        assert updated.usage_count == 1
        assert updated.success_rate == 0.0

    async def test_update_usage_returns_none_for_not_found(self, test_db: AsyncSession):
        """Test that update_usage returns None for non-existent composition."""
        repo = SQLToolCompositionRepository(test_db)

        result = await repo.update_usage("non-existent-id", success=True)

        assert result is None

    async def test_delete(self, test_db: AsyncSession):
        """Test deleting a composition."""
        repo = SQLToolCompositionRepository(test_db)

        composition = ToolComposition.create(
            name="Delete Test",
            description="Test deletion",
            tools=["tool1"],
        )

        await repo.save(composition)
        assert await repo.get_by_id(composition.id) is not None

        # Delete
        deleted = await repo.delete(composition.id)

        assert deleted is True
        assert await repo.get_by_id(composition.id) is None

    async def test_delete_returns_false_for_not_found(self, test_db: AsyncSession):
        """Test that delete returns False for non-existent composition."""
        repo = SQLToolCompositionRepository(test_db)

        deleted = await repo.delete("non-existent-id")

        assert deleted is False

    async def test_success_rate_calculation(self, test_db: AsyncSession):
        """Test success rate is calculated correctly."""
        repo = SQLToolCompositionRepository(test_db)

        composition = ToolComposition.create(
            name="Success Rate Test",
            description="Test success rate calculation",
            tools=["tool1"],
        )

        saved = await repo.save(composition)

        # Record 7 successes and 3 failures
        for _ in range(7):
            saved = await repo.update_usage(composition.id, success=True)
        for _ in range(3):
            saved = await repo.update_usage(composition.id, success=False)

        assert saved.success_count == 7
        assert saved.failure_count == 3
        assert saved.usage_count == 10
        assert saved.success_rate == 0.7
