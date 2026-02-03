"""
Tests for V2 SqlPlanRepository using BaseRepository.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.plan import Plan, PlanDocumentStatus
from src.infrastructure.adapters.secondary.persistence.sql_plan_repository import (
    SqlPlanRepository,
)


@pytest.fixture
async def v2_plan_repo(v2_db_session: AsyncSession) -> SqlPlanRepository:
    """Create a V2 plan repository for testing."""
    return SqlPlanRepository(v2_db_session)


def make_plan(
    plan_id: str,
    conversation_id: str,
    status: PlanDocumentStatus = PlanDocumentStatus.DRAFT,
    title: str = "Test Plan",
) -> Plan:
    """Factory for creating Plan objects."""
    return Plan(
        id=plan_id,
        conversation_id=conversation_id,
        title=title,
        content=f"Content for {title}",
        status=status,
        version=1,
        metadata={"key": "value"},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


class TestSqlPlanRepositoryCreate:
    """Tests for creating plans."""

    @pytest.mark.asyncio
    async def test_save_new_plan(self, v2_plan_repo: SqlPlanRepository):
        """Test saving a new plan."""
        plan = make_plan("plan-test-1", "conv-1")

        await v2_plan_repo.save(plan)

        result = await v2_plan_repo.find_by_id("plan-test-1")
        assert result is not None
        assert result.title == "Test Plan"

    @pytest.mark.asyncio
    async def test_save_updates_existing(self, v2_plan_repo: SqlPlanRepository):
        """Test saving updates an existing plan."""
        plan = make_plan("plan-update-1", "conv-1", title="Original")
        await v2_plan_repo.save(plan)

        plan.title = "Updated"
        plan.content = "New content"
        plan.version = 2

        await v2_plan_repo.save(plan)

        result = await v2_plan_repo.find_by_id("plan-update-1")
        assert result.title == "Updated"
        assert result.content == "New content"


class TestSqlPlanRepositoryFind:
    """Tests for finding plans."""

    @pytest.mark.asyncio
    async def test_find_by_id_existing(self, v2_plan_repo: SqlPlanRepository):
        """Test finding a plan by ID."""
        plan = make_plan("plan-find-1", "conv-1", title="Find me")
        await v2_plan_repo.save(plan)

        result = await v2_plan_repo.find_by_id("plan-find-1")
        assert result is not None
        assert result.title == "Find me"

    @pytest.mark.asyncio
    async def test_find_by_id_not_found(self, v2_plan_repo: SqlPlanRepository):
        """Test finding a non-existent plan returns None."""
        result = await v2_plan_repo.find_by_id("non-existent")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_by_conversation_id(self, v2_plan_repo: SqlPlanRepository):
        """Test finding plans by conversation ID."""
        for i in range(3):
            plan = make_plan(f"plan-conv-{i}", "conv-list-1", title=f"Plan {i}")
            await v2_plan_repo.save(plan)

        results = await v2_plan_repo.find_by_conversation_id("conv-list-1")
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_find_by_conversation_with_status(self, v2_plan_repo: SqlPlanRepository):
        """Test finding plans by conversation ID and status."""
        plan1 = make_plan("plan-status-1", "conv-status-1", PlanDocumentStatus.DRAFT)
        plan2 = make_plan("plan-status-2", "conv-status-1", PlanDocumentStatus.APPROVED)
        await v2_plan_repo.save(plan1)
        await v2_plan_repo.save(plan2)

        results = await v2_plan_repo.find_by_conversation_id("conv-status-1", PlanDocumentStatus.DRAFT)
        assert len(results) == 1
        assert results[0].status == PlanDocumentStatus.DRAFT

    @pytest.mark.asyncio
    async def test_find_active_by_conversation(self, v2_plan_repo: SqlPlanRepository):
        """Test finding active plan by conversation ID."""
        draft_plan = make_plan("plan-active-1", "conv-active-1", PlanDocumentStatus.DRAFT)
        archived_plan = make_plan("plan-active-2", "conv-active-1", PlanDocumentStatus.ARCHIVED)
        await v2_plan_repo.save(draft_plan)
        await v2_plan_repo.save(archived_plan)

        result = await v2_plan_repo.find_active_by_conversation("conv-active-1")
        assert result is not None
        assert result.status == PlanDocumentStatus.DRAFT


class TestSqlPlanRepositoryDelete:
    """Tests for deleting plans."""

    @pytest.mark.asyncio
    async def test_delete_by_id(self, v2_plan_repo: SqlPlanRepository):
        """Test deleting a plan by ID."""
        plan = make_plan("plan-delete-1", "conv-1")
        await v2_plan_repo.save(plan)

        await v2_plan_repo.delete("plan-delete-1")

        result = await v2_plan_repo.find_by_id("plan-delete-1")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_by_conversation(self, v2_plan_repo: SqlPlanRepository):
        """Test deleting all plans for a conversation."""
        for i in range(3):
            plan = make_plan(f"plan-del-conv-{i}", "conv-del-1")
            await v2_plan_repo.save(plan)

        await v2_plan_repo.delete_by_conversation("conv-del-1")

        results = await v2_plan_repo.find_by_conversation_id("conv-del-1")
        assert len(results) == 0


class TestSqlPlanRepositoryUpdate:
    """Tests for updating plans."""

    @pytest.mark.asyncio
    async def test_update_content(self, v2_plan_repo: SqlPlanRepository):
        """Test updating plan content."""
        plan = make_plan("plan-update-content-1", "conv-1")
        await v2_plan_repo.save(plan)

        result = await v2_plan_repo.update_content("plan-update-content-1", "New content")
        assert result is not None
        assert result.content == "New content"
        assert result.version == 2

    @pytest.mark.asyncio
    async def test_update_content_nonexistent(self, v2_plan_repo: SqlPlanRepository):
        """Test updating content of non-existent plan returns None."""
        result = await v2_plan_repo.update_content("non-existent", "content")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_status(self, v2_plan_repo: SqlPlanRepository):
        """Test updating plan status."""
        plan = make_plan("plan-update-status-1", "conv-1", PlanDocumentStatus.DRAFT)
        await v2_plan_repo.save(plan)

        result = await v2_plan_repo.update_status("plan-update-status-1", PlanDocumentStatus.APPROVED)
        assert result is not None
        assert result.status == PlanDocumentStatus.APPROVED

    @pytest.mark.asyncio
    async def test_update_status_nonexistent(self, v2_plan_repo: SqlPlanRepository):
        """Test updating status of non-existent plan returns None."""
        result = await v2_plan_repo.update_status("non-existent", PlanDocumentStatus.APPROVED)
        assert result is None


class TestSqlPlanRepositoryCount:
    """Tests for counting plans."""

    @pytest.mark.asyncio
    async def test_count_by_conversation(self, v2_plan_repo: SqlPlanRepository):
        """Test counting plans for a conversation."""
        for i in range(3):
            plan = make_plan(f"plan-count-{i}", "conv-count-1")
            await v2_plan_repo.save(plan)

        count = await v2_plan_repo.count_by_conversation("conv-count-1")
        assert count == 3

    @pytest.mark.asyncio
    async def test_count_empty_conversation(self, v2_plan_repo: SqlPlanRepository):
        """Test counting plans for conversation with no plans."""
        count = await v2_plan_repo.count_by_conversation("conv-empty")
        assert count == 0
