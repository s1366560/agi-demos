"""Unit tests for the WorkPlan domain entity."""

import pytest

from src.domain.model.agent import (
    PlanStatus,
    WorkPlan,
)
from src.domain.model.agent.plan_step import PlanStep


class TestWorkPlan:
    """Test WorkPlan domain entity behavior."""

    def test_create_work_plan_with_defaults(self):
        """Test creating a work plan with default values."""
        steps = [
            PlanStep(
                step_number=0,
                description="Search for memories",
                thought_prompt="What should I search for?",
                required_tools=["memory_search"],
                expected_output="List of relevant memories",
                dependencies=[],
            ),
        ]

        work_plan = WorkPlan(
            id="plan-1",
            conversation_id="conv-1",
            status=PlanStatus.PLANNING,
            steps=steps,
        )

        assert work_plan.id == "plan-1"
        assert work_plan.conversation_id == "conv-1"
        assert work_plan.status == PlanStatus.PLANNING
        assert len(work_plan.steps) == 1
        assert work_plan.current_step_index == 0
        assert work_plan.workflow_pattern_id is None

    def test_create_work_plan_with_workflow_pattern(self):
        """Test creating a work plan with a workflow pattern reference."""
        steps = [
            PlanStep(
                step_number=0,
                description="Step 1",
                thought_prompt="Think about step 1",
                required_tools=["tool1"],
                expected_output="Result 1",
                dependencies=[],
            ),
        ]

        work_plan = WorkPlan(
            id="plan-1",
            conversation_id="conv-1",
            status=PlanStatus.IN_PROGRESS,
            steps=steps,
            workflow_pattern_id="pattern-123",
        )

        assert work_plan.workflow_pattern_id == "pattern-123"
        assert work_plan.status == PlanStatus.IN_PROGRESS

    def test_get_current_step(self):
        """Test getting the current step being executed."""
        steps = [
            PlanStep(
                step_number=0,
                description="Step 1",
                thought_prompt="Think 1",
                required_tools=["tool1"],
                expected_output="Result 1",
                dependencies=[],
            ),
            PlanStep(
                step_number=1,
                description="Step 2",
                thought_prompt="Think 2",
                required_tools=["tool2"],
                expected_output="Result 2",
                dependencies=[0],
            ),
        ]

        work_plan = WorkPlan(
            id="plan-1",
            conversation_id="conv-1",
            status=PlanStatus.IN_PROGRESS,
            steps=steps,
            current_step_index=0,
        )

        current = work_plan.get_current_step()
        assert current is not None
        assert current.step_number == 0
        assert current.description == "Step 1"

    def test_get_current_step_out_of_bounds(self):
        """Test getting current step when index is out of bounds."""
        steps = [
            PlanStep(
                step_number=0,
                description="Step 1",
                thought_prompt="Think 1",
                required_tools=["tool1"],
                expected_output="Result 1",
                dependencies=[],
            ),
        ]

        work_plan = WorkPlan(
            id="plan-1",
            conversation_id="conv-1",
            status=PlanStatus.IN_PROGRESS,
            steps=steps,
            current_step_index=5,  # Out of bounds
        )

        assert work_plan.get_current_step() is None

    def test_get_next_step(self):
        """Test getting the next step to execute."""
        steps = [
            PlanStep(
                step_number=0,
                description="Step 1",
                thought_prompt="Think 1",
                required_tools=["tool1"],
                expected_output="Result 1",
                dependencies=[],
            ),
            PlanStep(
                step_number=1,
                description="Step 2",
                thought_prompt="Think 2",
                required_tools=["tool2"],
                expected_output="Result 2",
                dependencies=[0],
            ),
        ]

        work_plan = WorkPlan(
            id="plan-1",
            conversation_id="conv-1",
            status=PlanStatus.IN_PROGRESS,
            steps=steps,
            current_step_index=0,
        )

        next_step = work_plan.get_next_step()
        assert next_step is not None
        assert next_step.step_number == 1
        assert next_step.description == "Step 2"

    def test_get_next_step_at_end(self):
        """Test getting next step when at the last step."""
        steps = [
            PlanStep(
                step_number=0,
                description="Step 1",
                thought_prompt="Think 1",
                required_tools=["tool1"],
                expected_output="Result 1",
                dependencies=[],
            ),
        ]

        work_plan = WorkPlan(
            id="plan-1",
            conversation_id="conv-1",
            status=PlanStatus.IN_PROGRESS,
            steps=steps,
            current_step_index=0,
        )

        assert work_plan.get_next_step() is None

    def test_advance_step(self):
        """Test moving to the next step."""
        steps = [
            PlanStep(
                step_number=0,
                description="Step 1",
                thought_prompt="Think 1",
                required_tools=["tool1"],
                expected_output="Result 1",
                dependencies=[],
            ),
            PlanStep(
                step_number=1,
                description="Step 2",
                thought_prompt="Think 2",
                required_tools=["tool2"],
                expected_output="Result 2",
                dependencies=[0],
            ),
        ]

        work_plan = WorkPlan(
            id="plan-1",
            conversation_id="conv-1",
            status=PlanStatus.IN_PROGRESS,
            steps=steps,
            current_step_index=0,
        )

        work_plan.advance_step()
        assert work_plan.current_step_index == 1
        assert work_plan.updated_at is not None

    def test_advance_step_at_end(self):
        """Test that advancing at the end doesn't increment."""
        steps = [
            PlanStep(
                step_number=0,
                description="Step 1",
                thought_prompt="Think 1",
                required_tools=["tool1"],
                expected_output="Result 1",
                dependencies=[],
            ),
        ]

        work_plan = WorkPlan(
            id="plan-1",
            conversation_id="conv-1",
            status=PlanStatus.IN_PROGRESS,
            steps=steps,
            current_step_index=0,
        )

        work_plan.advance_step()
        # Should not increment because we're at the last step
        assert work_plan.current_step_index == 0

    def test_mark_in_progress(self):
        """Test marking the plan as in progress."""
        steps = [
            PlanStep(
                step_number=0,
                description="Step 1",
                thought_prompt="Think 1",
                required_tools=["tool1"],
                expected_output="Result 1",
                dependencies=[],
            ),
        ]

        work_plan = WorkPlan(
            id="plan-1",
            conversation_id="conv-1",
            status=PlanStatus.PLANNING,
            steps=steps,
        )

        work_plan.mark_in_progress()
        assert work_plan.status == PlanStatus.IN_PROGRESS
        assert work_plan.updated_at is not None

    def test_mark_completed(self):
        """Test marking the plan as completed."""
        steps = [
            PlanStep(
                step_number=0,
                description="Step 1",
                thought_prompt="Think 1",
                required_tools=["tool1"],
                expected_output="Result 1",
                dependencies=[],
            ),
        ]

        work_plan = WorkPlan(
            id="plan-1",
            conversation_id="conv-1",
            status=PlanStatus.IN_PROGRESS,
            steps=steps,
        )

        work_plan.mark_completed()
        assert work_plan.status == PlanStatus.COMPLETED
        assert work_plan.updated_at is not None

    def test_mark_failed(self):
        """Test marking the plan as failed."""
        steps = [
            PlanStep(
                step_number=0,
                description="Step 1",
                thought_prompt="Think 1",
                required_tools=["tool1"],
                expected_output="Result 1",
                dependencies=[],
            ),
        ]

        work_plan = WorkPlan(
            id="plan-1",
            conversation_id="conv-1",
            status=PlanStatus.IN_PROGRESS,
            steps=steps,
        )

        work_plan.mark_failed()
        assert work_plan.status == PlanStatus.FAILED
        assert work_plan.updated_at is not None

    def test_is_complete_property(self):
        """Test the is_complete property."""
        steps = [
            PlanStep(
                step_number=0,
                description="Step 1",
                thought_prompt="Think 1",
                required_tools=["tool1"],
                expected_output="Result 1",
                dependencies=[],
            ),
            PlanStep(
                step_number=1,
                description="Step 2",
                thought_prompt="Think 2",
                required_tools=["tool2"],
                expected_output="Result 2",
                dependencies=[0],
            ),
        ]

        work_plan = WorkPlan(
            id="plan-1",
            conversation_id="conv-1",
            status=PlanStatus.IN_PROGRESS,
            steps=steps,
            current_step_index=0,
        )

        # Not complete when no steps are in completed_step_indices
        assert not work_plan.is_complete

        # Complete when all steps are in completed_step_indices
        work_plan.completed_step_indices = {0, 1}
        assert work_plan.is_complete

    def test_is_complete_with_single_step(self):
        """Test is_complete with a single step plan."""
        steps = [
            PlanStep(
                step_number=0,
                description="Step 1",
                thought_prompt="Think 1",
                required_tools=["tool1"],
                expected_output="Result 1",
                dependencies=[],
            ),
        ]

        work_plan = WorkPlan(
            id="plan-1",
            conversation_id="conv-1",
            status=PlanStatus.IN_PROGRESS,
            steps=steps,
            current_step_index=0,
            completed_step_indices={0},
        )

        # Single step plan is complete when step 0 is in completed indices
        assert work_plan.is_complete

    def test_is_complete_with_empty_steps(self):
        """Test is_complete with no steps."""
        work_plan = WorkPlan(
            id="plan-1",
            conversation_id="conv-1",
            status=PlanStatus.PLANNING,
            steps=[],
            current_step_index=0,
        )

        # Empty plan is complete (nothing to do)
        assert work_plan.is_complete

    def test_progress_percentage_property(self):
        """Test the progress_percentage property."""
        steps = [
            PlanStep(
                step_number=0,
                description="Step 1",
                thought_prompt="Think 1",
                required_tools=["tool1"],
                expected_output="Result 1",
                dependencies=[],
            ),
            PlanStep(
                step_number=1,
                description="Step 2",
                thought_prompt="Think 2",
                required_tools=["tool2"],
                expected_output="Result 2",
                dependencies=[0],
            ),
            PlanStep(
                step_number=2,
                description="Step 3",
                thought_prompt="Think 3",
                required_tools=["tool3"],
                expected_output="Result 3",
                dependencies=[1],
            ),
        ]

        work_plan = WorkPlan(
            id="plan-1",
            conversation_id="conv-1",
            status=PlanStatus.IN_PROGRESS,
            steps=steps,
            current_step_index=0,
        )

        # No steps completed: 0/3 = 0%
        assert work_plan.progress_percentage == pytest.approx(0.0, abs=0.1)

        work_plan.completed_step_indices = {0}
        # 1 of 3 completed: 1/3 * 100 = 33.33%
        assert work_plan.progress_percentage == pytest.approx(33.33, rel=0.1)

        work_plan.completed_step_indices = {0, 1, 2}
        # All completed: 3/3 * 100 = 100%
        assert work_plan.progress_percentage == 100.0

    def test_progress_percentage_with_empty_steps(self):
        """Test progress_percentage with no steps."""
        work_plan = WorkPlan(
            id="plan-1",
            conversation_id="conv-1",
            status=PlanStatus.PLANNING,
            steps=[],
            current_step_index=0,
        )

        assert work_plan.progress_percentage == 100.0

    def test_to_dict(self):
        """Test converting work plan to dictionary."""
        steps = [
            PlanStep(
                step_number=0,
                description="Search memories",
                thought_prompt="What to search?",
                required_tools=["memory_search"],
                expected_output="Memories found",
                dependencies=[],
            ),
        ]

        work_plan = WorkPlan(
            id="plan-1",
            conversation_id="conv-1",
            status=PlanStatus.IN_PROGRESS,
            steps=steps,
            workflow_pattern_id="pattern-123",
        )

        result = work_plan.to_dict()

        assert result["id"] == "plan-1"
        assert result["conversation_id"] == "conv-1"
        assert result["status"] == "in_progress"
        assert len(result["steps"]) == 1
        assert result["current_step_index"] == 0
        assert result["workflow_pattern_id"] == "pattern-123"
        assert "created_at" in result
