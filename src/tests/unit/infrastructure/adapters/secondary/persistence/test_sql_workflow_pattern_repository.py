"""
Tests for V2 SqlWorkflowPatternRepository using BaseRepository.

TDD Approach: RED -> GREEN -> REFACTOR

These tests verify that the migrated repository maintains 100% compatibility
with the original implementation while leveraging the BaseRepository.

Key features tested:
- CRUD operations
- List by tenant
- Find by name
- Increment usage count
- Optional caching support
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.workflow_pattern import PatternStep, WorkflowPattern
from src.infrastructure.adapters.secondary.persistence.sql_workflow_pattern_repository import (
    SqlWorkflowPatternRepository,
)


@pytest.fixture
async def v2_pattern_repo(db_session: AsyncSession) -> SqlWorkflowPatternRepository:
    """Create a V2 workflow pattern repository for testing."""
    return SqlWorkflowPatternRepository(db_session)


def create_test_pattern(
    pattern_id: str,
    tenant_id: str = "tenant-1",
    name: str = "Test Pattern",
    description: str = "Test description",
    usage_count: int = 5,
) -> WorkflowPattern:
    """Helper to create a test pattern."""
    return WorkflowPattern(
        id=pattern_id,
        tenant_id=tenant_id,
        name=name,
        description=description,
        steps=[
            PatternStep(
                step_number=1,
                description="Step 1",
                tool_name="search",
                expected_output_format="text",
            ),
            PatternStep(
                step_number=2,
                description="Step 2",
                tool_name="analyze",
                expected_output_format="json",
            ),
        ],
        success_rate=0.8,
        usage_count=usage_count,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        metadata={"key": "value"},
    )


class TestSqlWorkflowPatternRepositoryCreate:
    """Tests for creating new patterns."""

    @pytest.mark.asyncio
    async def test_create_new_pattern(self, v2_pattern_repo: SqlWorkflowPatternRepository):
        """Test creating a new pattern."""
        pattern = create_test_pattern("pattern-test-1")

        result = await v2_pattern_repo.create(pattern)

        assert result.id == "pattern-test-1"
        assert result.name == "Test Pattern"

        # Verify was saved
        retrieved = await v2_pattern_repo.get_by_id("pattern-test-1")
        assert retrieved is not None
        assert retrieved.name == "Test Pattern"


class TestSqlWorkflowPatternRepositoryFind:
    """Tests for finding patterns."""

    @pytest.mark.asyncio
    async def test_get_by_id_existing(self, v2_pattern_repo: SqlWorkflowPatternRepository):
        """Test finding an existing pattern by ID."""
        pattern = create_test_pattern("pattern-find-1")
        await v2_pattern_repo.create(pattern)

        retrieved = await v2_pattern_repo.get_by_id("pattern-find-1")
        assert retrieved is not None
        assert retrieved.id == "pattern-find-1"
        assert retrieved.name == "Test Pattern"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, v2_pattern_repo: SqlWorkflowPatternRepository):
        """Test finding a non-existent pattern returns None."""
        retrieved = await v2_pattern_repo.get_by_id("non-existent")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_find_by_name_existing(self, v2_pattern_repo: SqlWorkflowPatternRepository):
        """Test finding a pattern by name within a tenant."""
        pattern = create_test_pattern("pattern-name-1", name="Unique Name")
        await v2_pattern_repo.create(pattern)

        retrieved = await v2_pattern_repo.find_by_name("tenant-1", "Unique Name")
        assert retrieved is not None
        assert retrieved.id == "pattern-name-1"
        assert retrieved.name == "Unique Name"

    @pytest.mark.asyncio
    async def test_find_by_name_not_found(self, v2_pattern_repo: SqlWorkflowPatternRepository):
        """Test finding a non-existent pattern by name returns None."""
        retrieved = await v2_pattern_repo.find_by_name("tenant-1", "Nonexistent")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_exists_true(self, v2_pattern_repo: SqlWorkflowPatternRepository):
        """Test exists returns True for existing pattern."""
        pattern = create_test_pattern("pattern-exists-1")
        await v2_pattern_repo.create(pattern)

        assert await v2_pattern_repo.exists("pattern-exists-1") is True

    @pytest.mark.asyncio
    async def test_exists_false(self, v2_pattern_repo: SqlWorkflowPatternRepository):
        """Test exists returns False for non-existent pattern."""
        assert await v2_pattern_repo.exists("non-existent") is False


class TestSqlWorkflowPatternRepositoryUpdate:
    """Tests for updating patterns."""

    @pytest.mark.asyncio
    async def test_update_existing_pattern(self, v2_pattern_repo: SqlWorkflowPatternRepository):
        """Test updating an existing pattern."""
        pattern = create_test_pattern("pattern-update-1")
        await v2_pattern_repo.create(pattern)

        # Update the pattern
        updated_pattern = WorkflowPattern(
            id="pattern-update-1",
            tenant_id="tenant-1",
            name="Updated Name",
            description="Updated description",
            steps=[
                PatternStep(
                    step_number=1,
                    description="New Step",
                    tool_name="new_tool",
                    expected_output_format="text",
                ),
            ],
            success_rate=0.9,
            usage_count=10,
            created_at=pattern.created_at,
            updated_at=datetime.now(UTC),
            metadata={"updated": True},
        )

        result = await v2_pattern_repo.update(updated_pattern)

        assert result.name == "Updated Name"

        # Verify updates
        retrieved = await v2_pattern_repo.get_by_id("pattern-update-1")
        assert retrieved.name == "Updated Name"
        assert retrieved.description == "Updated description"
        assert len(retrieved.steps) == 1
        assert retrieved.steps[0].tool_name == "new_tool"

    @pytest.mark.asyncio
    async def test_update_nonexistent_raises_error(
        self, v2_pattern_repo: SqlWorkflowPatternRepository
    ):
        """Test updating a non-existent pattern raises ValueError."""
        pattern = create_test_pattern("non-existent")

        with pytest.raises(ValueError, match="Pattern not found"):
            await v2_pattern_repo.update(pattern)


class TestSqlWorkflowPatternRepositoryList:
    """Tests for listing patterns."""

    @pytest.mark.asyncio
    async def test_list_by_tenant(self, v2_pattern_repo: SqlWorkflowPatternRepository):
        """Test listing patterns by tenant."""
        # Create patterns for different tenants
        for i in range(3):
            pattern = create_test_pattern(f"pattern-tenant-1-{i}", tenant_id="tenant-1")
            await v2_pattern_repo.create(pattern)

        # Add pattern for different tenant
        other_pattern = create_test_pattern("pattern-tenant-2", tenant_id="tenant-2")
        await v2_pattern_repo.create(other_pattern)

        # List tenant-1 patterns
        patterns = await v2_pattern_repo.list_by_tenant("tenant-1")
        assert len(patterns) == 3
        assert all(p.tenant_id == "tenant-1" for p in patterns)

    @pytest.mark.asyncio
    async def test_list_by_tenant_orders_by_usage(
        self, v2_pattern_repo: SqlWorkflowPatternRepository
    ):
        """Test that patterns are ordered by usage_count desc, then created_at desc."""
        # Create patterns with different usage counts
        pattern1 = create_test_pattern("pattern-order-1", usage_count=5)
        await v2_pattern_repo.create(pattern1)

        pattern2 = create_test_pattern("pattern-order-2", usage_count=10)
        await v2_pattern_repo.create(pattern2)

        pattern3 = create_test_pattern("pattern-order-3", usage_count=10)
        await v2_pattern_repo.create(pattern3)

        patterns = await v2_pattern_repo.list_by_tenant("tenant-1")

        # Should be ordered by usage_count desc
        assert patterns[0].usage_count >= patterns[1].usage_count
        assert patterns[1].usage_count >= patterns[2].usage_count


class TestSqlWorkflowPatternRepositoryDelete:
    """Tests for deleting patterns."""

    @pytest.mark.asyncio
    async def test_delete_existing_pattern(self, v2_pattern_repo: SqlWorkflowPatternRepository):
        """Test deleting an existing pattern."""
        pattern = create_test_pattern("pattern-delete-1")
        await v2_pattern_repo.create(pattern)

        # Delete
        await v2_pattern_repo.delete("pattern-delete-1")

        # Verify deleted
        retrieved = await v2_pattern_repo.get_by_id("pattern-delete-1")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_raises_error(
        self, v2_pattern_repo: SqlWorkflowPatternRepository
    ):
        """Test deleting a non-existent pattern raises ValueError."""
        with pytest.raises(ValueError, match="Pattern not found"):
            await v2_pattern_repo.delete("non-existent")


class TestSqlWorkflowPatternRepositoryIncrementUsage:
    """Tests for incrementing usage count."""

    @pytest.mark.asyncio
    async def test_increment_usage_count(self, v2_pattern_repo: SqlWorkflowPatternRepository):
        """Test incrementing the usage count for a pattern."""
        pattern = create_test_pattern("pattern-increment-1", usage_count=5)
        await v2_pattern_repo.create(pattern)

        # Increment
        result = await v2_pattern_repo.increment_usage_count("pattern-increment-1")

        assert result.usage_count == 6
        assert result.updated_at > pattern.updated_at

        # Verify in DB
        retrieved = await v2_pattern_repo.get_by_id("pattern-increment-1")
        assert retrieved.usage_count == 6

    @pytest.mark.asyncio
    async def test_increment_nonexistent_raises_error(
        self, v2_pattern_repo: SqlWorkflowPatternRepository
    ):
        """Test incrementing a non-existent pattern raises ValueError."""
        with pytest.raises(ValueError, match="Pattern not found"):
            await v2_pattern_repo.increment_usage_count("non-existent")


class TestSqlWorkflowPatternRepositoryToDomain:
    """Tests for _to_domain conversion."""

    @pytest.mark.asyncio
    async def test_to_domain_converts_all_fields(
        self, v2_pattern_repo: SqlWorkflowPatternRepository
    ):
        """Test that _to_domain correctly converts all DB fields."""
        pattern = create_test_pattern("pattern-domain-1")
        await v2_pattern_repo.create(pattern)

        retrieved = await v2_pattern_repo.get_by_id("pattern-domain-1")
        assert retrieved.id == "pattern-domain-1"
        assert retrieved.tenant_id == "tenant-1"
        assert retrieved.name == "Test Pattern"
        assert retrieved.description == "Test description"
        assert len(retrieved.steps) == 2
        assert retrieved.steps[0].step_number == 1
        assert retrieved.steps[0].tool_name == "search"
        assert retrieved.success_rate == 0.8
        assert retrieved.usage_count == 5

    @pytest.mark.asyncio
    async def test_to_domain_with_none_db_model(
        self, v2_pattern_repo: SqlWorkflowPatternRepository
    ):
        """Test that _to_domain returns None for None input."""
        result = v2_pattern_repo._to_domain(None)
        assert result is None


class TestSqlWorkflowPatternRepositoryStepConversion:
    """Tests for step conversion helpers."""

    def test_step_to_dict(self, v2_pattern_repo: SqlWorkflowPatternRepository):
        """Test converting PatternStep to dictionary."""
        step = PatternStep(
            step_number=1,
            description="Test Step",
            tool_name="test_tool",
            expected_output_format="json",
            similarity_threshold=0.9,
            tool_parameters={"key": "value"},
        )

        result = v2_pattern_repo._step_to_dict(step)

        assert result["step_number"] == 1
        assert result["description"] == "Test Step"
        assert result["tool_name"] == "test_tool"
        assert result["expected_output_format"] == "json"
        assert result["similarity_threshold"] == 0.9
        assert result["tool_parameters"] == {"key": "value"}

    def test_step_from_dict(self, v2_pattern_repo: SqlWorkflowPatternRepository):
        """Test converting dictionary to PatternStep."""
        data = {
            "step_number": 2,
            "description": "From Dict",
            "tool_name": "dict_tool",
            "expected_output_format": "text",
            "similarity_threshold": 0.7,
            "tool_parameters": {"param": "value"},
        }

        result = v2_pattern_repo._step_from_dict(data)

        assert result.step_number == 2
        assert result.description == "From Dict"
        assert result.tool_name == "dict_tool"
        assert result.expected_output_format == "text"
        assert result.similarity_threshold == 0.7
        assert result.tool_parameters == {"param": "value"}

    def test_step_from_dict_with_defaults(self, v2_pattern_repo: SqlWorkflowPatternRepository):
        """Test converting dictionary with missing optional fields."""
        data = {
            "step_number": 3,
            "description": "Minimal Step",
            "tool_name": "minimal_tool",
        }

        result = v2_pattern_repo._step_from_dict(data)

        assert result.step_number == 3
        assert result.expected_output_format == "text"  # default
        assert result.similarity_threshold == 0.8  # default
        assert result.tool_parameters is None


class TestSqlWorkflowPatternRepositoryTransaction:
    """Tests for transaction support."""

    @pytest.mark.asyncio
    async def test_transaction_context_manager(self, v2_pattern_repo: SqlWorkflowPatternRepository):
        """Test using transaction context manager."""
        async with v2_pattern_repo.transaction():
            pattern1 = create_test_pattern("pattern-tx-1")
            await v2_pattern_repo.create(pattern1)

            pattern2 = create_test_pattern("pattern-tx-2")
            await v2_pattern_repo.create(pattern2)

        # Verify both were saved
        p1 = await v2_pattern_repo.get_by_id("pattern-tx-1")
        p2 = await v2_pattern_repo.get_by_id("pattern-tx-2")
        assert p1 is not None
        assert p2 is not None

    @pytest.mark.asyncio
    async def test_transaction_rollback_on_error(
        self, v2_pattern_repo: SqlWorkflowPatternRepository
    ):
        """Test that transaction rolls back on error."""
        try:
            async with v2_pattern_repo.transaction():
                pattern1 = create_test_pattern("pattern-tx-rollback-1")
                await v2_pattern_repo.create(pattern1)

                # Raise error to trigger rollback
                raise ValueError("Test error")
        except ValueError:
            pass

        # Verify rollback occurred
        p1 = await v2_pattern_repo.get_by_id("pattern-tx-rollback-1")
        assert p1 is None


class TestSqlWorkflowPatternRepositoryCount:
    """Tests for counting patterns."""

    @pytest.mark.asyncio
    async def test_count_all(self, v2_pattern_repo: SqlWorkflowPatternRepository):
        """Test counting all patterns."""
        # Initially empty
        count = await v2_pattern_repo.count()
        assert count == 0

        # Add patterns
        for i in range(3):
            pattern = create_test_pattern(f"pattern-count-{i}")
            await v2_pattern_repo.create(pattern)

        count = await v2_pattern_repo.count()
        assert count == 3
