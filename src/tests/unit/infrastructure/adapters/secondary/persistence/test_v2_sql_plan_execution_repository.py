"""
Tests for V2 SqlPlanExecutionRepository using BaseRepository.
"""

import pytest
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.plan_execution import (
    ExecutionMode,
    ExecutionStatus,
    ExecutionStep,
    PlanExecution,
)
from src.infrastructure.adapters.secondary.persistence.v2_sql_plan_execution_repository import (
    V2SqlPlanExecutionRepository,
)


@pytest.fixture
async def v2_plan_execution_repo(v2_db_session: AsyncSession) -> V2SqlPlanExecutionRepository:
    """Create a V2 plan execution repository for testing."""
    return V2SqlPlanExecutionRepository(v2_db_session)


def make_execution_step(step_number: int, description: str) -> ExecutionStep:
    """Factory for creating ExecutionStep objects."""
    return ExecutionStep(
        step_id=f"step-{step_number}",
        step_number=step_number,
        description=description,
        thought_prompt=f"Think about {description}",
        expected_output=f"Output for {description}",
        tool_name="test_tool",
        tool_input={},
        dependencies=[],
    )


def make_plan_execution(
    execution_id: str,
    conversation_id: str,
    plan_id: str,
    status: ExecutionStatus = ExecutionStatus.PENDING,
) -> PlanExecution:
    """Factory for creating PlanExecution objects."""
    return PlanExecution(
        id=execution_id,
        conversation_id=conversation_id,
        plan_id=plan_id,
        steps=[
            make_execution_step(0, "First step"),
            make_execution_step(1, "Second step"),
        ],
        current_step_index=0,
        completed_step_indices=[],
        failed_step_indices=[],
        status=status,
        execution_mode=ExecutionMode.SEQUENTIAL,
        max_parallel_steps=1,
        reflection_enabled=False,
        max_reflection_cycles=3,
        current_reflection_cycle=0,
        workflow_pattern_id=None,
        metadata={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        started_at=None,
        completed_at=None,
    )


class TestV2SqlPlanExecutionRepositoryCreate:
    """Tests for creating plan executions."""

    @pytest.mark.asyncio
    async def test_save_new_execution(self, v2_plan_execution_repo: V2SqlPlanExecutionRepository):
        """Test saving a new plan execution."""
        execution = make_plan_execution("exec-test-1", "conv-1", "plan-1")

        result = await v2_plan_execution_repo.save(execution)

        assert result.id == "exec-test-1"
        assert len(result.steps) == 2
        assert result.status == ExecutionStatus.PENDING

    @pytest.mark.asyncio
    async def test_save_updates_existing(self, v2_plan_execution_repo: V2SqlPlanExecutionRepository):
        """Test saving updates an existing execution."""
        execution = make_plan_execution("exec-update-1", "conv-1", "plan-1")
        await v2_plan_execution_repo.save(execution)

        execution.status = ExecutionStatus.RUNNING
        execution.current_step_index = 1
        execution.completed_step_indices = [0]

        result = await v2_plan_execution_repo.save(execution)
        assert result.status == ExecutionStatus.RUNNING
        assert result.current_step_index == 1


class TestV2SqlPlanExecutionRepositoryFind:
    """Tests for finding executions."""

    @pytest.mark.asyncio
    async def test_find_by_id_existing(self, v2_plan_execution_repo: V2SqlPlanExecutionRepository):
        """Test finding an execution by ID."""
        execution = make_plan_execution("exec-find-1", "conv-1", "plan-1")
        await v2_plan_execution_repo.save(execution)

        result = await v2_plan_execution_repo.find_by_id("exec-find-1")
        assert result is not None
        assert result.plan_id == "plan-1"

    @pytest.mark.asyncio
    async def test_find_by_id_not_found(self, v2_plan_execution_repo: V2SqlPlanExecutionRepository):
        """Test finding a non-existent execution returns None."""
        result = await v2_plan_execution_repo.find_by_id("non-existent")
        assert result is None

    @pytest.mark.asyncio
    async def test_find_by_plan_id(self, v2_plan_execution_repo: V2SqlPlanExecutionRepository):
        """Test finding executions by plan ID."""
        for i in range(3):
            execution = make_plan_execution(f"exec-plan-{i}", "conv-1", "plan-find-1")
            await v2_plan_execution_repo.save(execution)

        results = await v2_plan_execution_repo.find_by_plan_id("plan-find-1")
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_find_by_conversation(self, v2_plan_execution_repo: V2SqlPlanExecutionRepository):
        """Test finding executions by conversation ID."""
        for i in range(3):
            execution = make_plan_execution(f"exec-conv-{i}", "conv-find-1", f"plan-{i}")
            await v2_plan_execution_repo.save(execution)

        results = await v2_plan_execution_repo.find_by_conversation("conv-find-1")
        assert len(results) == 3

    @pytest.mark.asyncio
    async def test_find_by_conversation_with_status(self, v2_plan_execution_repo: V2SqlPlanExecutionRepository):
        """Test finding executions by conversation ID and status."""
        exec1 = make_plan_execution("exec-status-1", "conv-status-1", "plan-1", ExecutionStatus.RUNNING)
        exec2 = make_plan_execution("exec-status-2", "conv-status-1", "plan-2", ExecutionStatus.COMPLETED)
        await v2_plan_execution_repo.save(exec1)
        await v2_plan_execution_repo.save(exec2)

        results = await v2_plan_execution_repo.find_by_conversation("conv-status-1", ExecutionStatus.RUNNING)
        assert len(results) == 1
        assert results[0].status == ExecutionStatus.RUNNING

    @pytest.mark.asyncio
    async def test_find_active_by_conversation(self, v2_plan_execution_repo: V2SqlPlanExecutionRepository):
        """Test finding active execution by conversation ID."""
        exec1 = make_plan_execution("exec-active-1", "conv-active-1", "plan-1", ExecutionStatus.RUNNING)
        exec2 = make_plan_execution("exec-active-2", "conv-active-1", "plan-2", ExecutionStatus.COMPLETED)
        await v2_plan_execution_repo.save(exec1)
        await v2_plan_execution_repo.save(exec2)

        result = await v2_plan_execution_repo.find_active_by_conversation("conv-active-1")
        assert result is not None
        assert result.status == ExecutionStatus.RUNNING


class TestV2SqlPlanExecutionRepositoryUpdate:
    """Tests for updating executions."""

    @pytest.mark.asyncio
    async def test_update_status(self, v2_plan_execution_repo: V2SqlPlanExecutionRepository):
        """Test updating execution status."""
        execution = make_plan_execution("exec-update-status-1", "conv-1", "plan-1")
        await v2_plan_execution_repo.save(execution)

        result = await v2_plan_execution_repo.update_status("exec-update-status-1", ExecutionStatus.RUNNING)
        assert result is not None
        assert result.status == ExecutionStatus.RUNNING

    @pytest.mark.asyncio
    async def test_update_status_nonexistent(self, v2_plan_execution_repo: V2SqlPlanExecutionRepository):
        """Test updating status of non-existent execution returns None."""
        result = await v2_plan_execution_repo.update_status("non-existent", ExecutionStatus.RUNNING)
        assert result is None

    @pytest.mark.asyncio
    async def test_update_step(self, v2_plan_execution_repo: V2SqlPlanExecutionRepository):
        """Test updating a step within an execution."""
        execution = make_plan_execution("exec-update-step-1", "conv-1", "plan-1")
        await v2_plan_execution_repo.save(execution)

        # Update step data
        step_data = {
            "step_id": execution.steps[0].step_id,
            "step_number": 0,
            "description": "Updated step",
            "thought_prompt": execution.steps[0].thought_prompt,
            "expected_output": execution.steps[0].expected_output,
            "tool_name": execution.steps[0].tool_name,
            "tool_input": execution.steps[0].tool_input,
            "dependencies": execution.steps[0].dependencies,
        }

        result = await v2_plan_execution_repo.update_step("exec-update-step-1", 0, step_data)
        assert result is not None
        # The step should be updated in the database
        assert result is not None

    @pytest.mark.asyncio
    async def test_update_step_nonexistent(self, v2_plan_execution_repo: V2SqlPlanExecutionRepository):
        """Test updating step of non-existent execution returns None."""
        result = await v2_plan_execution_repo.update_step("non-existent", 0, {})
        assert result is None


class TestV2SqlPlanExecutionRepositoryDelete:
    """Tests for deleting executions."""

    @pytest.mark.asyncio
    async def test_delete_existing(self, v2_plan_execution_repo: V2SqlPlanExecutionRepository):
        """Test deleting an existing execution."""
        execution = make_plan_execution("exec-delete-1", "conv-1", "plan-1")
        await v2_plan_execution_repo.save(execution)

        result = await v2_plan_execution_repo.delete("exec-delete-1")
        assert result is True

        retrieved = await v2_plan_execution_repo.find_by_id("exec-delete-1")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, v2_plan_execution_repo: V2SqlPlanExecutionRepository):
        """Test deleting a non-existent execution returns False."""
        result = await v2_plan_execution_repo.delete("non-existent")
        assert result is False
