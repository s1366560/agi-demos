"""
Unit tests for ExecutionPlan domain model.

Tests follow TDD: Write first, verify FAIL, implement, verify PASS.
"""

from datetime import datetime, timezone
from unittest.mock import Mock

import pytest

from src.domain.model.agent.execution_plan import (
    ExecutionPlan,
    ExecutionStep,
    ExecutionStepStatus,
    ExecutionPlanStatus,
)


class TestExecutionStepStatus:
    """Tests for ExecutionStepStatus enum."""

    def test_status_values(self) -> None:
        """Test that status enum has all expected values."""
        assert ExecutionStepStatus.PENDING.value == "pending"
        assert ExecutionStepStatus.RUNNING.value == "running"
        assert ExecutionStepStatus.COMPLETED.value == "completed"
        assert ExecutionStepStatus.FAILED.value == "failed"
        assert ExecutionStepStatus.SKIPPED.value == "skipped"
        assert ExecutionStepStatus.CANCELLED.value == "cancelled"

    def test_status_from_string(self) -> None:
        """Test creating status from string value."""
        assert ExecutionStepStatus("pending") == ExecutionStepStatus.PENDING
        assert ExecutionStepStatus("running") == ExecutionStepStatus.RUNNING
        assert ExecutionStepStatus("completed") == ExecutionStepStatus.COMPLETED
        assert ExecutionStepStatus("failed") == ExecutionStepStatus.FAILED
        assert ExecutionStepStatus("skipped") == ExecutionStepStatus.SKIPPED
        assert ExecutionStepStatus("cancelled") == ExecutionStepStatus.CANCELLED


class TestExecutionPlanStatus:
    """Tests for ExecutionPlanStatus enum."""

    def test_status_values(self) -> None:
        """Test that status enum has all expected values."""
        assert ExecutionPlanStatus.DRAFT.value == "draft"
        assert ExecutionPlanStatus.APPROVED.value == "approved"
        assert ExecutionPlanStatus.EXECUTING.value == "executing"
        assert ExecutionPlanStatus.PAUSED.value == "paused"
        assert ExecutionPlanStatus.COMPLETED.value == "completed"
        assert ExecutionPlanStatus.FAILED.value == "failed"
        assert ExecutionPlanStatus.CANCELLED.value == "cancelled"


class TestExecutionStep:
    """Tests for ExecutionStep value object."""

    def test_create_step_with_required_fields(self) -> None:
        """Test creating a step with minimal required fields."""
        step = ExecutionStep(
            step_id="step-1",
            description="Search memory",
            tool_name="MemorySearch",
        )

        assert step.step_id == "step-1"
        assert step.description == "Search memory"
        assert step.tool_name == "MemorySearch"
        assert step.status == ExecutionStepStatus.PENDING
        assert step.tool_input == {}
        assert step.dependencies == []
        assert step.result is None
        assert step.error is None

    def test_create_step_with_all_fields(self) -> None:
        """Test creating a step with all fields."""
        now = datetime.now(timezone.utc)
        step = ExecutionStep(
            step_id="step-2",
            description="Create memory",
            tool_name="MemoryCreate",
            tool_input={"content": "test"},
            dependencies=["step-1"],
            status=ExecutionStepStatus.RUNNING,
            result="Created successfully",
            started_at=now,
        )

        assert step.step_id == "step-2"
        assert step.description == "Create memory"
        assert step.tool_name == "MemoryCreate"
        assert step.tool_input == {"content": "test"}
        assert step.dependencies == ["step-1"]
        assert step.status == ExecutionStepStatus.RUNNING
        assert step.result == "Created successfully"
        assert step.started_at == now

    def test_step_is_immutable(self) -> None:
        """Test that ExecutionStep is immutable (frozen)."""
        from dataclasses import FrozenInstanceError

        step = ExecutionStep(
            step_id="step-1",
            description="Test step",
            tool_name="TestTool",
        )

        with pytest.raises(FrozenInstanceError):
            step.description = "Modified"

    def test_mark_started_creates_new_instance(self) -> None:
        """Test that mark_started returns a new step with RUNNING status."""
        step = ExecutionStep(
            step_id="step-1",
            description="Test step",
            tool_name="TestTool",
        )

        started_step = step.mark_started()

        # Original unchanged (immutability)
        assert step.status == ExecutionStepStatus.PENDING
        assert step.started_at is None

        # New instance has updated values
        assert started_step.status == ExecutionStepStatus.RUNNING
        assert started_step.started_at is not None
        assert started_step.started_at <= datetime.now(timezone.utc)

    def test_mark_completed_creates_new_instance(self) -> None:
        """Test that mark_completed returns a new step with result."""
        step = ExecutionStep(
            step_id="step-1",
            description="Test step",
            tool_name="TestTool",
            status=ExecutionStepStatus.RUNNING,
        )

        result = "Operation completed"
        completed_step = step.mark_completed(result)

        # Original unchanged
        assert step.status == ExecutionStepStatus.RUNNING
        assert step.result is None

        # New instance updated
        assert completed_step.status == ExecutionStepStatus.COMPLETED
        assert completed_step.result == result
        assert completed_step.completed_at is not None

    def test_mark_failed_creates_new_instance(self) -> None:
        """Test that mark_failed returns a new step with error."""
        step = ExecutionStep(
            step_id="step-1",
            description="Test step",
            tool_name="TestTool",
            status=ExecutionStepStatus.RUNNING,
        )

        error_msg = "Connection timeout"
        failed_step = step.mark_failed(error_msg)

        assert failed_step.status == ExecutionStepStatus.FAILED
        assert failed_step.error == error_msg
        assert failed_step.completed_at is not None

    def test_mark_skipped_creates_new_instance(self) -> None:
        """Test that mark_skipped returns a new step."""
        step = ExecutionStep(
            step_id="step-1",
            description="Test step",
            tool_name="TestTool",
        )

        skipped_step = step.mark_skipped("Condition not met")

        assert skipped_step.status == ExecutionStepStatus.SKIPPED
        assert skipped_step.error == "Condition not met"

    def test_is_ready_with_no_dependencies(self) -> None:
        """Test is_ready when step has no dependencies."""
        step = ExecutionStep(
            step_id="step-1",
            description="Test step",
            tool_name="TestTool",
        )

        assert step.is_ready(completed_steps=set()) is True

    def test_is_ready_with_unmet_dependencies(self) -> None:
        """Test is_ready when dependencies are not met."""
        step = ExecutionStep(
            step_id="step-2",
            description="Test step",
            tool_name="TestTool",
            dependencies=["step-1"],
        )

        assert step.is_ready(completed_steps=set()) is False
        assert step.is_ready(completed_steps={"step-3"}) is False

    def test_is_ready_with_met_dependencies(self) -> None:
        """Test is_ready when all dependencies are met."""
        step = ExecutionStep(
            step_id="step-2",
            description="Test step",
            tool_name="TestTool",
            dependencies=["step-1"],
        )

        assert step.is_ready(completed_steps={"step-1"}) is True

    def test_is_ready_with_multiple_dependencies(self) -> None:
        """Test is_ready with multiple dependencies."""
        step = ExecutionStep(
            step_id="step-3",
            description="Test step",
            tool_name="TestTool",
            dependencies=["step-1", "step-2"],
        )

        assert step.is_ready(completed_steps={"step-1"}) is False
        assert step.is_ready(completed_steps={"step-1", "step-2"}) is True

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        step = ExecutionStep(
            step_id="step-1",
            description="Test step",
            tool_name="TestTool",
            tool_input={"key": "value"},
            dependencies=[],
        )

        result = step.to_dict()

        assert result["step_id"] == "step-1"
        assert result["description"] == "Test step"
        assert result["tool_name"] == "TestTool"
        assert result["tool_input"] == {"key": "value"}
        assert result["dependencies"] == []
        assert result["status"] == "pending"
        assert result["result"] is None
        assert result["error"] is None


class TestExecutionPlan:
    """Tests for ExecutionPlan entity."""

    def test_create_plan_with_required_fields(self) -> None:
        """Test creating a plan with minimal fields."""
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Find recent memories",
            steps=[],
        )

        assert plan.conversation_id == "conv-1"
        assert plan.user_query == "Find recent memories"
        assert plan.steps == []
        assert plan.status == ExecutionPlanStatus.DRAFT
        assert plan.reflection_enabled is True
        assert plan.max_reflection_cycles == 3
        assert plan.completed_steps == []
        assert plan.failed_steps == []
        assert plan.snapshot is None

    def test_create_plan_with_all_fields(self) -> None:
        """Test creating a plan with all fields."""
        step = ExecutionStep(
            step_id="step-1",
            description="Search",
            tool_name="MemorySearch",
        )
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Find recent memories",
            steps=[step],
            status=ExecutionPlanStatus.EXECUTING,
            reflection_enabled=False,
            max_reflection_cycles=1,
            completed_steps=["step-0"],
            failed_steps=[],
        )

        assert len(plan.steps) == 1
        assert plan.status == ExecutionPlanStatus.EXECUTING
        assert plan.reflection_enabled is False
        assert plan.max_reflection_cycles == 1

    def test_get_ready_steps_with_no_dependencies(self) -> None:
        """Test getting ready steps when none have dependencies."""
        steps = [
            ExecutionStep(step_id="step-1", description="A", tool_name="Tool1"),
            ExecutionStep(step_id="step-2", description="B", tool_name="Tool2"),
        ]
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=steps,
        )

        ready = plan.get_ready_steps()
        assert len(ready) == 2
        assert "step-1" in ready
        assert "step-2" in ready

    def test_get_ready_steps_with_dependencies(self) -> None:
        """Test getting ready steps respecting dependencies."""
        steps = [
            ExecutionStep(step_id="step-1", description="A", tool_name="Tool1"),
            ExecutionStep(
                step_id="step-2",
                description="B",
                tool_name="Tool2",
                dependencies=["step-1"],
            ),
        ]
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=steps,
        )

        # Initially only step-1 is ready
        ready = plan.get_ready_steps()
        assert ready == ["step-1"]

    def test_get_ready_steps_after_completion(self) -> None:
        """Test getting ready steps after dependency completes."""
        steps = [
            ExecutionStep(
                step_id="step-1",
                description="A",
                tool_name="Tool1",
                status=ExecutionStepStatus.COMPLETED,  # Step 1 already completed
            ),
            ExecutionStep(
                step_id="step-2",
                description="B",
                tool_name="Tool2",
                dependencies=["step-1"],
            ),
        ]
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=steps,
            completed_steps=["step-1"],
        )

        ready = plan.get_ready_steps()
        assert ready == ["step-2"]

    def test_get_ready_steps_ignores_completed(self) -> None:
        """Test that completed steps are not returned as ready."""
        steps = [
            ExecutionStep(
                step_id="step-1",
                description="A",
                tool_name="Tool1",
                status=ExecutionStepStatus.COMPLETED,
            ),
        ]
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=steps,
            completed_steps=["step-1"],
        )

        ready = plan.get_ready_steps()
        assert ready == []

    def test_get_ready_steps_ignores_failed(self) -> None:
        """Test that failed steps are not returned as ready."""
        steps = [
            ExecutionStep(
                step_id="step-1",
                description="A",
                tool_name="Tool1",
                status=ExecutionStepStatus.FAILED,
            ),
        ]
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=steps,
            failed_steps=["step-1"],
        )

        ready = plan.get_ready_steps()
        assert ready == []

    def test_update_step_replaces_step(self) -> None:
        """Test updating a step in the plan."""
        original_step = ExecutionStep(
            step_id="step-1",
            description="Original",
            tool_name="Tool1",
        )
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[original_step],
        )

        updated_step = original_step.mark_started()
        new_plan = plan.update_step(updated_step)

        # New plan has updated step
        assert new_plan.steps[0].status == ExecutionStepStatus.RUNNING
        # Original plan unchanged (immutability)
        assert plan.steps[0].status == ExecutionStepStatus.PENDING

    def test_mark_step_completed(self) -> None:
        """Test marking a step as completed."""
        step = ExecutionStep(
            step_id="step-1",
            description="Test",
            tool_name="Tool1",
            status=ExecutionStepStatus.RUNNING,
        )
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[step],
        )

        new_plan = plan.mark_step_completed("step-1", "Result text")

        assert "step-1" in new_plan.completed_steps
        assert new_plan.steps[0].status == ExecutionStepStatus.COMPLETED
        assert new_plan.steps[0].result == "Result text"

    def test_mark_step_failed(self) -> None:
        """Test marking a step as failed."""
        step = ExecutionStep(
            step_id="step-1",
            description="Test",
            tool_name="Tool1",
            status=ExecutionStepStatus.RUNNING,
        )
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[step],
        )

        new_plan = plan.mark_step_failed("step-1", "Error occurred")

        assert "step-1" in new_plan.failed_steps
        assert new_plan.steps[0].status == ExecutionStepStatus.FAILED
        assert new_plan.steps[0].error == "Error occurred"

    def test_mark_step_started(self) -> None:
        """Test marking a step as started."""
        step = ExecutionStep(
            step_id="step-1",
            description="Test",
            tool_name="Tool1",
        )
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[step],
        )

        new_plan = plan.mark_step_started("step-1")

        assert new_plan.steps[0].status == ExecutionStepStatus.RUNNING
        assert new_plan.steps[0].started_at is not None

    def test_mark_executing(self) -> None:
        """Test marking plan as executing."""
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[],
        )

        executing_plan = plan.mark_executing()

        assert executing_plan.status == ExecutionPlanStatus.EXECUTING
        assert executing_plan.started_at is not None

    def test_mark_completed(self) -> None:
        """Test marking plan as completed."""
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[],
            status=ExecutionPlanStatus.EXECUTING,
        )

        completed_plan = plan.mark_completed()

        assert completed_plan.status == ExecutionPlanStatus.COMPLETED
        assert completed_plan.completed_at is not None

    def test_mark_failed(self) -> None:
        """Test marking plan as failed."""
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[],
            status=ExecutionPlanStatus.EXECUTING,
        )

        failed_plan = plan.mark_failed("Critical error")

        assert failed_plan.status == ExecutionPlanStatus.FAILED
        assert failed_plan.error == "Critical error"
        assert failed_plan.completed_at is not None

    def test_mark_cancelled(self) -> None:
        """Test marking plan as cancelled."""
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[],
            status=ExecutionPlanStatus.EXECUTING,
        )

        cancelled_plan = plan.mark_cancelled()

        assert cancelled_plan.status == ExecutionPlanStatus.CANCELLED
        assert cancelled_plan.completed_at is not None

    def test_is_complete_with_no_steps(self) -> None:
        """Test is_complete when plan has no steps."""
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[],
        )

        assert plan.is_complete is True

    def test_is_complete_with_all_steps_completed(self) -> None:
        """Test is_complete when all steps are completed."""
        step = ExecutionStep(
            step_id="step-1",
            description="Test",
            tool_name="Tool1",
            status=ExecutionStepStatus.COMPLETED,
        )
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[step],
            completed_steps=["step-1"],
        )

        assert plan.is_complete is True

    def test_is_complete_with_pending_steps(self) -> None:
        """Test is_complete with pending steps."""
        step = ExecutionStep(
            step_id="step-1",
            description="Test",
            tool_name="Tool1",
        )
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[step],
        )

        assert plan.is_complete is False

    def test_is_complete_with_failed_steps(self) -> None:
        """Test is_complete when all remaining steps failed."""
        step = ExecutionStep(
            step_id="step-1",
            description="Test",
            tool_name="Tool1",
            status=ExecutionStepStatus.FAILED,
        )
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[step],
            failed_steps=["step-1"],
        )

        assert plan.is_complete is True

    def test_progress_percentage_with_no_steps(self) -> None:
        """Test progress with no steps."""
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[],
        )

        assert plan.progress_percentage == 100.0

    def test_progress_percentage_with_partial_completion(self) -> None:
        """Test progress with some steps completed."""
        steps = [
            ExecutionStep(step_id="step-1", description="A", tool_name="Tool1"),
            ExecutionStep(step_id="step-2", description="B", tool_name="Tool2"),
            ExecutionStep(step_id="step-3", description="C", tool_name="Tool3"),
        ]
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=steps,
            completed_steps=["step-1"],
        )

        assert plan.progress_percentage == pytest.approx(33.33, rel=0.1)

    def test_progress_percentage_with_failed_steps(self) -> None:
        """Test progress including failed steps as 'done'."""
        steps = [
            ExecutionStep(step_id="step-1", description="A", tool_name="Tool1"),
            ExecutionStep(step_id="step-2", description="B", tool_name="Tool2"),
        ]
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=steps,
            completed_steps=["step-1"],
            failed_steps=["step-2"],
        )

        assert plan.progress_percentage == 100.0

    def test_get_step_by_id(self) -> None:
        """Test retrieving a step by ID."""
        step = ExecutionStep(
            step_id="step-1",
            description="Test",
            tool_name="Tool1",
        )
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[step],
        )

        retrieved = plan.get_step_by_id("step-1")
        assert retrieved is not None
        assert retrieved.step_id == "step-1"

    def test_get_step_by_id_not_found(self) -> None:
        """Test retrieving non-existent step."""
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[],
        )

        assert plan.get_step_by_id("nonexistent") is None

    def test_create_snapshot(self) -> None:
        """Test creating a snapshot of the plan."""
        from src.domain.model.agent.plan_snapshot import PlanSnapshot, StepState

        step = ExecutionStep(
            step_id="step-1",
            description="Test",
            tool_name="Tool1",
        )
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[step],
        )

        snapshot = plan.create_snapshot(name="Checkpoint 1")

        assert isinstance(snapshot, PlanSnapshot)
        assert snapshot.name == "Checkpoint 1"
        assert snapshot.plan_id == plan.id
        assert len(snapshot.step_states) == 1
        # step_states contains StepState objects, not dicts
        assert isinstance(snapshot.step_states["step-1"], StepState)
        assert snapshot.step_states["step-1"].status == "pending"

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        step = ExecutionStep(
            step_id="step-1",
            description="Test",
            tool_name="Tool1",
        )
        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[step],
        )

        result = plan.to_dict()

        assert result["conversation_id"] == "conv-1"
        assert result["user_query"] == "Test"
        assert len(result["steps"]) == 1
        assert result["status"] == "draft"
        assert result["reflection_enabled"] is True
        assert result["max_reflection_cycles"] == 3
