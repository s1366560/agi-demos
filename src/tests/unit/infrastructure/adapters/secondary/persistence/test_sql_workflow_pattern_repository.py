"""
Unit tests for SQLWorkflowPatternRepository (T066)

Tests the SQL implementation of WorkflowPattern repository.
Updated to match actual implementation API.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.workflow_pattern import PatternStep, WorkflowPattern
from src.infrastructure.adapters.secondary.persistence.sql_workflow_pattern_repository import (
    SQLWorkflowPatternRepository,
)


@pytest.mark.asyncio
class TestSQLWorkflowPatternRepository:
    """Tests for SQLWorkflowPatternRepository."""

    async def test_create_pattern(self, test_db: AsyncSession):
        """Test creating a new workflow pattern."""
        repo = SQLWorkflowPatternRepository(test_db)

        pattern = WorkflowPattern(
            id="pattern-1",
            tenant_id="tenant-1",
            name="Test Pattern",
            description="A test pattern",
            steps=[
                PatternStep(
                    step_number=1,
                    description="Step 1",
                    tool_name="tool1",
                    expected_output_format="text",
                    similarity_threshold=0.8,
                )
            ],
            success_rate=1.0,
            usage_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        created = await repo.create(pattern)

        assert created.id == pattern.id
        assert created.name == "Test Pattern"
        assert created.tenant_id == "tenant-1"

    async def test_get_pattern_by_id(self, test_db: AsyncSession):
        """Test retrieving a pattern by ID."""
        repo = SQLWorkflowPatternRepository(test_db)

        pattern = WorkflowPattern(
            id="pattern-2",
            tenant_id="tenant-1",
            name="Get Test",
            description="Test get by id",
            steps=[],
            success_rate=1.0,
            usage_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        await repo.create(pattern)
        retrieved = await repo.get_by_id("pattern-2")

        assert retrieved is not None
        assert retrieved.id == "pattern-2"
        assert retrieved.name == "Get Test"

    async def test_get_pattern_returns_none_for_not_found(self, test_db: AsyncSession):
        """Test that get_by_id returns None for non-existent pattern."""
        repo = SQLWorkflowPatternRepository(test_db)

        retrieved = await repo.get_by_id("non-existent")

        assert retrieved is None

    async def test_list_patterns_by_tenant(self, test_db: AsyncSession):
        """Test listing all patterns for a tenant."""
        repo = SQLWorkflowPatternRepository(test_db)

        # Create patterns for two tenants
        pattern1 = WorkflowPattern(
            id="pattern-1",
            tenant_id="tenant-1",
            name="Tenant 1 Pattern 1",
            description="Pattern for tenant 1",
            steps=[],
            success_rate=1.0,
            usage_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        pattern2 = WorkflowPattern(
            id="pattern-2",
            tenant_id="tenant-1",
            name="Tenant 1 Pattern 2",
            description="Another pattern for tenant 1",
            steps=[],
            success_rate=0.9,
            usage_count=5,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        pattern3 = WorkflowPattern(
            id="pattern-3",
            tenant_id="tenant-2",
            name="Tenant 2 Pattern",
            description="Pattern for tenant 2",
            steps=[],
            success_rate=1.0,
            usage_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        await repo.create(pattern1)
        await repo.create(pattern2)
        await repo.create(pattern3)

        # List patterns for tenant-1
        tenant1_patterns = await repo.list_by_tenant("tenant-1")

        assert len(tenant1_patterns) == 2
        assert all(p.tenant_id == "tenant-1" for p in tenant1_patterns)

        # List patterns for tenant-2
        tenant2_patterns = await repo.list_by_tenant("tenant-2")

        assert len(tenant2_patterns) == 1
        assert tenant2_patterns[0].id == "pattern-3"

    async def test_list_patterns_ordered_by_usage_count(self, test_db: AsyncSession):
        """Test that patterns are ordered by usage count descending."""
        repo = SQLWorkflowPatternRepository(test_db)

        patterns = [
            WorkflowPattern(
                id=f"pattern-{i}",
                tenant_id="tenant-1",
                name=f"Pattern {i}",
                description=f"Pattern {i}",
                steps=[],
                success_rate=0.5 + (i * 0.1),
                usage_count=i * 10,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            for i in range(5)
        ]

        for pattern in patterns:
            await repo.create(pattern)

        result = await repo.list_by_tenant("tenant-1")

        # Should be ordered by usage_count descending
        usage_counts = [p.usage_count for p in result]
        assert usage_counts == sorted(usage_counts, reverse=True)

    async def test_find_by_name(self, test_db: AsyncSession):
        """Test finding a pattern by name within a tenant."""
        repo = SQLWorkflowPatternRepository(test_db)

        pattern = WorkflowPattern(
            id="pattern-1",
            tenant_id="tenant-1",
            name="Financial Analysis",
            description="Pattern for analyzing financial data",
            steps=[],
            success_rate=0.95,
            usage_count=10,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        await repo.create(pattern)

        # Find by name
        found = await repo.find_by_name("tenant-1", "Financial Analysis")

        assert found is not None
        assert found.id == "pattern-1"
        assert found.name == "Financial Analysis"

        # Find non-existent name
        not_found = await repo.find_by_name("tenant-1", "Non Existent")
        assert not_found is None

    async def test_update_pattern(self, test_db: AsyncSession):
        """Test updating an existing pattern."""
        repo = SQLWorkflowPatternRepository(test_db)

        pattern = WorkflowPattern(
            id="pattern-1",
            tenant_id="tenant-1",
            name="Original Name",
            description="Original description",
            steps=[],
            success_rate=0.8,
            usage_count=5,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        await repo.create(pattern)

        # Update the pattern
        updated = WorkflowPattern(
            id="pattern-1",
            tenant_id="tenant-1",
            name="Updated Name",
            description="Updated description",
            steps=[],
            success_rate=0.9,
            usage_count=6,
            created_at=pattern.created_at,
            updated_at=datetime.now(timezone.utc),
        )

        await repo.update(updated)

        # Verify the update
        retrieved = await repo.get_by_id("pattern-1")
        assert retrieved.name == "Updated Name"
        assert retrieved.description == "Updated description"
        assert retrieved.success_rate == 0.9
        assert retrieved.usage_count == 6

    async def test_delete_pattern(self, test_db: AsyncSession):
        """Test deleting a pattern."""
        repo = SQLWorkflowPatternRepository(test_db)

        pattern = WorkflowPattern(
            id="pattern-1",
            tenant_id="tenant-1",
            name="To Delete",
            description="Will be deleted",
            steps=[],
            success_rate=1.0,
            usage_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        await repo.create(pattern)

        # Delete the pattern
        await repo.delete("pattern-1")

        # Verify it's gone
        retrieved = await repo.get_by_id("pattern-1")
        assert retrieved is None

    async def test_increment_usage_count(self, test_db: AsyncSession):
        """Test incrementing pattern usage count."""
        repo = SQLWorkflowPatternRepository(test_db)

        pattern = WorkflowPattern(
            id="pattern-1",
            tenant_id="tenant-1",
            name="Test",
            description="Test",
            steps=[],
            success_rate=1.0,
            usage_count=5,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        await repo.create(pattern)

        # Increment usage count
        await repo.increment_usage_count("pattern-1")

        # Verify increment
        retrieved = await repo.get_by_id("pattern-1")
        assert retrieved.usage_count == 6
