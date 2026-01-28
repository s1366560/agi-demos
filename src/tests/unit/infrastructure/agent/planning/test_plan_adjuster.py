"""
Unit tests for PlanAdjuster.

TDD: Tests written first, implementation to follow.
Tests follow RED-GREEN-REFACTOR cycle.
"""

from unittest.mock import AsyncMock, Mock
from typing import Any

import pytest

from src.domain.model.agent.execution_plan import (
    ExecutionPlan,
    ExecutionStep,
    ExecutionStepStatus,
    ExecutionPlanStatus,
)
from src.domain.model.agent.reflection_result import (
    StepAdjustment,
    AdjustmentType,
)
from src.infrastructure.agent.planning.plan_adjuster import PlanAdjuster, AdjustmentError


class TestPlanAdjusterInit:
    """Tests for PlanAdjuster initialization."""

    def test_init(self) -> None:
        """Test creating PlanAdjuster."""
        adjuster = PlanAdjuster()

        assert adjuster is not None


class TestApplyAdjustments:
    """Tests for applying adjustments to plans."""

    def test_apply_modify_adjustment(self) -> None:
        """Test applying a MODIFY adjustment."""
        adjuster = PlanAdjuster()

        steps = [
            ExecutionStep(
                step_id="step-1",
                description="Search memory",
                tool_name="MemorySearch",
                tool_input={"query": "Python"},
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=steps,
        )

        adjustment = StepAdjustment(
            step_id="step-1",
            adjustment_type=AdjustmentType.MODIFY,
            reason="Query too broad",
            new_tool_input={"query": "Python programming", "limit": 10},
        )

        updated_plan = adjuster.apply_adjustment(plan, adjustment)

        # Should create a new plan (immutable)
        assert updated_plan is not plan
        updated_step = updated_plan.get_step_by_id("step-1")
        assert updated_step is not None
        assert updated_step.tool_input["query"] == "Python programming"
        assert updated_step.tool_input["limit"] == 10

    def test_apply_retry_adjustment(self) -> None:
        """Test applying a RETRY adjustment."""
        adjuster = PlanAdjuster()

        steps = [
            ExecutionStep(
                step_id="step-1",
                description="Search",
                tool_name="MemorySearch",
                tool_input={"query": "test"},
                status=ExecutionStepStatus.FAILED,
                error="Timeout",
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=steps,
            failed_steps=["step-1"],
        )

        adjustment = StepAdjustment(
            step_id="step-1",
            adjustment_type=AdjustmentType.RETRY,
            reason="Timeout was temporary",
            new_tool_input={"query": "test", "timeout": 60},
        )

        updated_plan = adjuster.apply_adjustment(plan, adjustment)

        # Step should be reset to PENDING
        updated_step = updated_plan.get_step_by_id("step-1")
        assert updated_step.status == ExecutionStepStatus.PENDING
        assert updated_step.error is None
        assert updated_step.result is None
        assert "step-1" not in updated_plan.failed_steps
        # New input should be applied
        assert updated_step.tool_input["timeout"] == 60

    def test_apply_skip_adjustment(self) -> None:
        """Test applying a SKIP adjustment."""
        adjuster = PlanAdjuster()

        steps = [
            ExecutionStep(
                step_id="step-1",
                description="Completed step",
                tool_name="MemorySearch",
                status=ExecutionStepStatus.COMPLETED,
                result="Done",
            ),
            ExecutionStep(
                step_id="step-2",
                description="To be skipped",
                tool_name="Summary",
                status=ExecutionStepStatus.PENDING,
            ),
            ExecutionStep(
                step_id="step-3",
                description="Final step",
                tool_name="Result",
                status=ExecutionStepStatus.PENDING,
                dependencies=["step-1", "step-2"],
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=steps,
            completed_steps=["step-1"],
        )

        adjustment = StepAdjustment(
            step_id="step-2",
            adjustment_type=AdjustmentType.SKIP,
            reason="No longer needed",
        )

        updated_plan = adjuster.apply_adjustment(plan, adjustment)

        # Step should be marked as skipped
        skipped_step = updated_plan.get_step_by_id("step-2")
        assert skipped_step.status == ExecutionStepStatus.SKIPPED
        assert "no longer needed" in skipped_step.error.lower()

        # Dependent step's dependencies should be updated
        final_step = updated_plan.get_step_by_id("step-3")
        assert final_step is not None
        # Dependencies should be updated (step-2 removed from dependencies)
        assert "step-2" not in final_step.dependencies

    def test_apply_add_before_adjustment(self) -> None:
        """Test applying an ADD_BEFORE adjustment."""
        adjuster = PlanAdjuster()

        steps = [
            ExecutionStep(
                step_id="step-1",
                description="Original step",
                tool_name="MemorySearch",
                tool_input={"query": "test"},
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=steps,
        )

        new_step = ExecutionStep(
            step_id="step-new",
            description="New step to add before",
            tool_name="EntityLookup",
            tool_input={"entity": "test"},
        )

        adjustment = StepAdjustment(
            step_id="step-1",
            adjustment_type=AdjustmentType.ADD_BEFORE,
            reason="Need to lookup entity first",
            new_step=new_step,
        )

        updated_plan = adjuster.apply_adjustment(plan, adjustment)

        # Should have 2 steps now
        assert len(updated_plan.steps) == 2
        # New step should come before original
        assert updated_plan.steps[0].step_id == "step-new"
        assert updated_plan.steps[1].step_id == "step-1"
        # Original step should depend on new step
        assert "step-new" in updated_plan.steps[1].dependencies

    def test_apply_add_after_adjustment(self) -> None:
        """Test applying an ADD_AFTER adjustment."""
        adjuster = PlanAdjuster()

        steps = [
            ExecutionStep(
                step_id="step-1",
                description="Original step",
                tool_name="MemorySearch",
                tool_input={"query": "test"},
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=steps,
        )

        new_step = ExecutionStep(
            step_id="step-new",
            description="New step to add after",
            tool_name="Summary",
            tool_input={},
        )

        adjustment = StepAdjustment(
            step_id="step-1",
            adjustment_type=AdjustmentType.ADD_AFTER,
            reason="Need to summarize results",
            new_step=new_step,
        )

        updated_plan = adjuster.apply_adjustment(plan, adjustment)

        # Should have 2 steps
        assert len(updated_plan.steps) == 2
        # New step should come after original
        assert updated_plan.steps[0].step_id == "step-1"
        assert updated_plan.steps[1].step_id == "step-new"
        # New step should depend on original
        assert "step-1" in updated_plan.steps[1].dependencies

    def test_apply_replace_adjustment(self) -> None:
        """Test applying a REPLACE adjustment."""
        adjuster = PlanAdjuster()

        steps = [
            ExecutionStep(
                step_id="step-1",
                description="Old step",
                tool_name="OldTool",
                tool_input={"arg": "value"},
                status=ExecutionStepStatus.FAILED,
                error="Old tool failed",
            ),
            ExecutionStep(
                step_id="step-2",
                description="Dependent step",
                tool_name="DependentTool",
                tool_input={},
                dependencies=["step-1"],
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=steps,
            failed_steps=["step-1"],
        )

        new_step = ExecutionStep(
            step_id="step-1",
            description="Replacement step",
            tool_name="NewTool",
            tool_input={"arg": "new value"},
        )

        adjustment = StepAdjustment(
            step_id="step-1",
            adjustment_type=AdjustmentType.REPLACE,
            reason="Old tool not working",
            new_step=new_step,
        )

        updated_plan = adjuster.apply_adjustment(plan, adjustment)

        # Should have same number of steps
        assert len(updated_plan.steps) == 2
        # First step should be replaced
        replaced_step = updated_plan.get_step_by_id("step-1")
        assert replaced_step.description == "Replacement step"
        assert replaced_step.tool_name == "NewTool"
        assert replaced_step.status == ExecutionStepStatus.PENDING
        assert replaced_step.error is None
        # Dependency should be maintained
        assert "step-1" in updated_plan.steps[1].dependencies
        # Failed steps should be cleared
        assert "step-1" not in updated_plan.failed_steps

    def test_apply_unknown_adjustment_type(self) -> None:
        """Test applying an unknown adjustment type."""
        adjuster = PlanAdjuster()

        steps = [
            ExecutionStep(
                step_id="step-1",
                description="Test",
                tool_name="TestTool",
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=steps,
        )

        # Create a mock adjustment with unknown type
        adjustment = Mock()
        adjustment.adjustment_type = "unknown_type"
        adjustment.step_id = "step-1"

        with pytest.raises(ValueError, match="Unknown adjustment type"):
            adjuster.apply_adjustment(plan, adjustment)


class TestApplyMultipleAdjustments:
    """Tests for applying multiple adjustments."""

    def test_apply_multiple_adjustments(self) -> None:
        """Test applying multiple adjustments at once."""
        adjuster = PlanAdjuster()

        steps = [
            ExecutionStep(
                step_id="step-1",
                description="First",
                tool_name="Tool1",
                status=ExecutionStepStatus.COMPLETED,
                result="Done",
            ),
            ExecutionStep(
                step_id="step-2",
                description="Second",
                tool_name="Tool2",
                status=ExecutionStepStatus.FAILED,
                error="Failed",
            ),
            ExecutionStep(
                step_id="step-3",
                description="Third",
                tool_name="Tool3",
                status=ExecutionStepStatus.PENDING,
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=steps,
            completed_steps=["step-1"],
            failed_steps=["step-2"],
        )

        adjustments = [
            StepAdjustment(
                step_id="step-2",
                adjustment_type=AdjustmentType.RETRY,
                reason="Retry with different params",
                new_tool_input={"retry": True},
            ),
            StepAdjustment(
                step_id="step-3",
                adjustment_type=AdjustmentType.SKIP,
                reason="Not needed",
            ),
        ]

        updated_plan = adjuster.apply_adjustments(plan, adjustments)

        # Both adjustments should be applied
        step_2 = updated_plan.get_step_by_id("step-2")
        assert step_2.status == ExecutionStepStatus.PENDING
        assert step_2.tool_input["retry"] is True

        step_3 = updated_plan.get_step_by_id("step-3")
        assert step_3.status == ExecutionStepStatus.SKIPPED

    def test_apply_adjustments_in_order(self) -> None:
        """Test that adjustments are applied in order."""
        adjuster = PlanAdjuster()

        steps = [
            ExecutionStep(
                step_id="step-1",
                description="Original",
                tool_name="Tool1",
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=steps,
        )

        adjustments = [
            StepAdjustment(
                step_id="step-1",
                adjustment_type=AdjustmentType.MODIFY,
                reason="First modification",
                new_tool_input={"v": 1},
            ),
            StepAdjustment(
                step_id="step-1",
                adjustment_type=AdjustmentType.MODIFY,
                reason="Second modification",
                new_tool_input={"v": 2},
            ),
        ]

        updated_plan = adjuster.apply_adjustments(plan, adjustments)

        # Last adjustment should win
        step = updated_plan.get_step_by_id("step-1")
        assert step.tool_input["v"] == 2


class TestImmutability:
    """Tests for ensuring immutability."""

    def test_apply_adjustment_does_not_mutate_original(self) -> None:
        """Test that applying adjustment doesn't mutate original plan."""
        adjuster = PlanAdjuster()

        original_steps = [
            ExecutionStep(
                step_id="step-1",
                description="Original",
                tool_name="Tool",
                tool_input={"key": "original"},
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=original_steps,
        )

        original_step = plan.get_step_by_id("step-1")

        adjustment = StepAdjustment(
            step_id="step-1",
            adjustment_type=AdjustmentType.MODIFY,
            reason="Update",
            new_tool_input={"key": "modified"},
        )

        updated_plan = adjuster.apply_adjustment(plan, adjustment)

        # Original plan should be unchanged
        assert plan.get_step_by_id("step-1").tool_input["key"] == "original"
        assert original_step.tool_input["key"] == "original"

        # Updated plan should have new value
        assert updated_plan.get_step_by_id("step-1").tool_input["key"] == "modified"

    def test_apply_multiple_does_not_mutate_original(self) -> None:
        """Test that applying multiple adjustments doesn't mutate original."""
        adjuster = PlanAdjuster()

        steps = [
            ExecutionStep(
                step_id="step-1",
                description="Test",
                tool_name="Tool",
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=steps,
        )

        original_completed = list(plan.completed_steps)

        adjustments = [
            StepAdjustment(
                step_id="step-1",
                adjustment_type=AdjustmentType.SKIP,
                reason="Skip",
            ),
        ]

        updated_plan = adjuster.apply_adjustments(plan, adjustments)

        # Original should be unchanged
        assert plan.completed_steps == original_completed
        assert len(plan.completed_steps) == 0

        # Updated should have changes
        updated_step = updated_plan.get_step_by_id("step-1")
        assert updated_step.status == ExecutionStepStatus.SKIPPED


class TestEdgeCases:
    """Tests for edge cases."""

    def test_apply_adjustment_to_nonexistent_step(self) -> None:
        """Test applying adjustment to step that doesn't exist."""
        adjuster = PlanAdjuster()

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[],
        )

        adjustment = StepAdjustment(
            step_id="nonexistent",
            adjustment_type=AdjustmentType.MODIFY,
            reason="Test",
        )

        with pytest.raises(AdjustmentError, match="Step not found"):
            adjuster.apply_adjustment(plan, adjustment)

    def test_apply_add_before_to_empty_plan(self) -> None:
        """Test adding before step in empty plan."""
        adjuster = PlanAdjuster()

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=[],
        )

        new_step = ExecutionStep(
            step_id="step-new",
            description="New",
            tool_name="Tool",
        )

        adjustment = StepAdjustment(
            step_id="step-1",  # Doesn't exist
            adjustment_type=AdjustmentType.ADD_BEFORE,
            reason="Test",
            new_step=new_step,
        )

        with pytest.raises(AdjustmentError, match="Step not found"):
            adjuster.apply_adjustment(plan, adjustment)

    def test_apply_adjustment_without_new_step_for_add(self) -> None:
        """Test ADD_BEFORE/ADD_AFTER without new_step."""
        adjuster = PlanAdjuster()

        steps = [
            ExecutionStep(
                step_id="step-1",
                description="Test",
                tool_name="Tool",
            ),
        ]

        plan = ExecutionPlan(
            conversation_id="conv-1",
            user_query="Test",
            steps=steps,
        )

        adjustment = StepAdjustment(
            step_id="step-1",
            adjustment_type=AdjustmentType.ADD_BEFORE,
            reason="Test",
            # Missing new_step
        )

        with pytest.raises(AdjustmentError, match="new_step required"):
            adjuster.apply_adjustment(plan, adjustment)
