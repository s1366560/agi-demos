"""
Tests for V2 SqlWorkPlanRepository using BaseRepository.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import PlanStatus, PlanStep, WorkPlan
from src.infrastructure.adapters.secondary.persistence.sql_work_plan_repository import (
    SqlWorkPlanRepository,
)


@pytest.fixture
async def v2_work_plan_repo(v2_db_session: AsyncSession) -> SqlWorkPlanRepository:
    """Create a V2 work plan repository for testing."""
    return SqlWorkPlanRepository(v2_db_session)


def make_plan_step(step_number: int, description: str) -> PlanStep:
    """Factory for creating PlanStep objects."""
    return PlanStep(
        step_number=step_number,
        description=description,
        thought_prompt=f"Think about {description}",
        required_tools=[],
        expected_output=f"Output for {description}",
        dependencies=[],
    )


class TestSqlWorkPlanRepositoryCreate:
    """Tests for creating work plans."""

    @pytest.mark.asyncio
    async def test_save_new_plan(self, v2_work_plan_repo: SqlWorkPlanRepository):
        """Test saving a new work plan."""
        steps = [
            make_plan_step(0, "First step"),
            make_plan_step(1, "Second step"),
        ]
        plan = WorkPlan(
            id="plan-test-1",
            conversation_id="conv-1",
            status=PlanStatus.PLANNING,
            steps=steps,
            current_step_index=0,
            workflow_pattern_id=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

        result = await v2_work_plan_repo.save(plan)

        assert result.id == "plan-test-1"
        assert len(result.steps) == 2
        assert result.status == PlanStatus.PLANNING

    @pytest.mark.asyncio
    async def test_save_updates_existing(self, v2_work_plan_repo: SqlWorkPlanRepository):
        """Test saving updates an existing plan."""
        steps = [make_plan_step(0, "Original step")]
        plan = WorkPlan(
            id="plan-update-1",
            conversation_id="conv-1",
            status=PlanStatus.PLANNING,
            steps=steps,
            current_step_index=0,
            workflow_pattern_id=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_work_plan_repo.save(plan)

        plan.status = PlanStatus.IN_PROGRESS
        plan.current_step_index = 1
        plan.steps.append(make_plan_step(1, "New step"))

        result = await v2_work_plan_repo.save(plan)
        assert result.status == PlanStatus.IN_PROGRESS
        assert result.current_step_index == 1


class TestSqlWorkPlanRepositoryFind:
    """Tests for finding plans."""

    @pytest.mark.asyncio
    async def test_get_by_id_existing(self, v2_work_plan_repo: SqlWorkPlanRepository):
        """Test getting a plan by ID."""
        steps = [make_plan_step(0, "Find me")]
        plan = WorkPlan(
            id="plan-find-1",
            conversation_id="conv-1",
            status=PlanStatus.IN_PROGRESS,
            steps=steps,
            current_step_index=0,
            workflow_pattern_id="pattern-1",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_work_plan_repo.save(plan)

        result = await v2_work_plan_repo.get_by_id("plan-find-1")
        assert result is not None
        assert result.conversation_id == "conv-1"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, v2_work_plan_repo: SqlWorkPlanRepository):
        """Test getting a non-existent plan returns None."""
        result = await v2_work_plan_repo.get_by_id("non-existent")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_conversation(self, v2_work_plan_repo: SqlWorkPlanRepository):
        """Test getting plans by conversation ID."""
        for i in range(3):
            steps = [make_plan_step(i, f"Step {i}")]
            plan = WorkPlan(
                id=f"plan-conv-{i}",
                conversation_id="conv-list-1",
                status=PlanStatus.PLANNING,
                steps=steps,
                current_step_index=0,
                workflow_pattern_id=None,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await v2_work_plan_repo.save(plan)

        results = await v2_work_plan_repo.get_by_conversation("conv-list-1")
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_get_active_by_conversation(self, v2_work_plan_repo: SqlWorkPlanRepository):
        """Test getting active plan by conversation ID."""
        # Create completed plan
        completed_steps = [make_plan_step(0, "Completed")]
        completed_plan = WorkPlan(
            id="plan-completed-1",
            conversation_id="conv-active-1",
            status=PlanStatus.COMPLETED,
            steps=completed_steps,
            current_step_index=1,
            workflow_pattern_id=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_work_plan_repo.save(completed_plan)

        # Create in-progress plan
        active_steps = [make_plan_step(0, "Active")]
        active_plan = WorkPlan(
            id="plan-active-1",
            conversation_id="conv-active-1",
            status=PlanStatus.IN_PROGRESS,
            steps=active_steps,
            current_step_index=0,
            workflow_pattern_id=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_work_plan_repo.save(active_plan)

        result = await v2_work_plan_repo.get_active_by_conversation("conv-active-1")
        assert result is not None
        assert result.id == "plan-active-1"
        assert result.status == PlanStatus.IN_PROGRESS


class TestSqlWorkPlanRepositoryDelete:
    """Tests for deleting plans."""

    @pytest.mark.asyncio
    async def test_delete_existing(self, v2_work_plan_repo: SqlWorkPlanRepository):
        """Test deleting an existing plan."""
        steps = [make_plan_step(0, "Delete me")]
        plan = WorkPlan(
            id="plan-delete-1",
            conversation_id="conv-1",
            status=PlanStatus.PLANNING,
            steps=steps,
            current_step_index=0,
            workflow_pattern_id=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await v2_work_plan_repo.save(plan)

        result = await v2_work_plan_repo.delete("plan-delete-1")
        assert result is True

        retrieved = await v2_work_plan_repo.get_by_id("plan-delete-1")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, v2_work_plan_repo: SqlWorkPlanRepository):
        """Test deleting a non-existent plan returns False."""
        result = await v2_work_plan_repo.delete("non-existent")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_by_conversation(self, v2_work_plan_repo: SqlWorkPlanRepository):
        """Test deleting all plans for a conversation."""
        for i in range(3):
            steps = [make_plan_step(i, f"Step {i}")]
            plan = WorkPlan(
                id=f"plan-del-conv-{i}",
                conversation_id="conv-del-1",
                status=PlanStatus.PLANNING,
                steps=steps,
                current_step_index=0,
                workflow_pattern_id=None,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await v2_work_plan_repo.save(plan)

        await v2_work_plan_repo.delete_by_conversation("conv-del-1")

        results = await v2_work_plan_repo.get_by_conversation("conv-del-1")
        assert len(results) == 0
