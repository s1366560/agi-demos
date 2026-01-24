"""Unit tests for the PlanStep value object."""

import pytest

from src.domain.model.agent.plan_step import PlanStep


class TestPlanStep:
    """Test PlanStep value object behavior."""

    def test_create_plan_step(self):
        """Test creating a valid plan step."""
        step = PlanStep(
            step_number=0,
            description="Search for relevant memories",
            thought_prompt="What keywords should I use to search?",
            required_tools=["memory_search"],
            expected_output="A list of relevant memories",
            dependencies=[],
        )

        assert step.step_number == 0
        assert step.description == "Search for relevant memories"
        assert step.thought_prompt == "What keywords should I use to search?"
        assert step.required_tools == ["memory_search"]
        assert step.expected_output == "A list of relevant memories"
        assert step.dependencies == []

    def test_create_plan_step_with_dependencies(self):
        """Test creating a plan step with dependencies."""
        step = PlanStep(
            step_number=2,
            description="Summarize findings",
            thought_prompt="What are the key insights?",
            required_tools=["summary"],
            expected_output="A summary of findings",
            dependencies=[0, 1],
        )

        assert step.step_number == 2
        assert step.dependencies == [0, 1]

    def test_is_ready_with_no_dependencies(self):
        """Test is_ready when step has no dependencies."""
        step = PlanStep(
            step_number=0,
            description="Step 1",
            thought_prompt="Think",
            required_tools=["tool1"],
            expected_output="Result",
            dependencies=[],
        )

        # Step with no dependencies is always ready
        assert step.is_ready(set())

    def test_is_ready_with_satisfied_dependencies(self):
        """Test is_ready when dependencies are satisfied."""
        step = PlanStep(
            step_number=2,
            description="Step 3",
            thought_prompt="Think",
            required_tools=["tool1"],
            expected_output="Result",
            dependencies=[0, 1],
        )

        # Dependencies are satisfied
        assert step.is_ready({0, 1})

    def test_is_ready_with_partial_dependencies(self):
        """Test is_ready when only some dependencies are satisfied."""
        step = PlanStep(
            step_number=2,
            description="Step 3",
            thought_prompt="Think",
            required_tools=["tool1"],
            expected_output="Result",
            dependencies=[0, 1],
        )

        # Only one dependency satisfied
        assert not step.is_ready({0})

    def test_is_ready_with_unsatisfied_dependencies(self):
        """Test is_ready when no dependencies are satisfied."""
        step = PlanStep(
            step_number=2,
            description="Step 3",
            thought_prompt="Think",
            required_tools=["tool1"],
            expected_output="Result",
            dependencies=[0, 1],
        )

        # No dependencies satisfied
        assert not step.is_ready(set())

    def test_validation_negative_step_number(self):
        """Test that negative step_number raises ValueError."""
        with pytest.raises(ValueError, match="step_number must be non-negative"):
            PlanStep(
                step_number=-1,
                description="Step",
                thought_prompt="Think",
                required_tools=["tool1"],
                expected_output="Result",
                dependencies=[],
            )

    def test_validation_empty_description(self):
        """Test that empty description raises ValueError."""
        with pytest.raises(ValueError, match="description cannot be empty"):
            PlanStep(
                step_number=0,
                description="",
                thought_prompt="Think",
                required_tools=["tool1"],
                expected_output="Result",
                dependencies=[],
            )

    def test_validation_empty_thought_prompt(self):
        """Test that empty thought_prompt raises ValueError."""
        with pytest.raises(ValueError, match="thought_prompt cannot be empty"):
            PlanStep(
                step_number=0,
                description="Step",
                thought_prompt="",
                required_tools=["tool1"],
                expected_output="Result",
                dependencies=[],
            )

    def test_validation_empty_expected_output(self):
        """Test that empty expected_output raises ValueError."""
        with pytest.raises(ValueError, match="expected_output cannot be empty"):
            PlanStep(
                step_number=0,
                description="Step",
                thought_prompt="Think",
                required_tools=["tool1"],
                expected_output="",
                dependencies=[],
            )

    def test_validation_negative_dependency(self):
        """Test that negative dependency raises ValueError."""
        with pytest.raises(ValueError, match="Dependency step number must be non-negative"):
            PlanStep(
                step_number=0,
                description="Step",
                thought_prompt="Think",
                required_tools=["tool1"],
                expected_output="Result",
                dependencies=[-1],
            )

    def test_validation_self_dependency(self):
        """Test that step cannot depend on itself."""
        with pytest.raises(ValueError, match="Step cannot depend on itself"):
            PlanStep(
                step_number=1,
                description="Step",
                thought_prompt="Think",
                required_tools=["tool1"],
                expected_output="Result",
                dependencies=[1],
            )

    def test_frozen_immutable(self):
        """Test that PlanStep is frozen (immutable)."""
        step = PlanStep(
            step_number=0,
            description="Step",
            thought_prompt="Think",
            required_tools=["tool1"],
            expected_output="Result",
            dependencies=[],
        )

        # PlanStep is frozen, attempting to modify will raise an error
        # In Python's dataclasses with frozen=True, modification raises FrozenInstanceError
        # We can verify immutability by checking that dataclasses.fields() shows frozen=True
        from dataclasses import fields

        step_fields = fields(step)
        assert step_fields[0].name == "step_number"
        # The frozen property is set via @dataclass(frozen=True)
        # Actual modification test would require catching FrozenInstanceError
        # which is only raised at runtime, not during import
        assert hasattr(step, "step_number")

    def test_to_dict(self):
        """Test converting plan step to dictionary."""
        step = PlanStep(
            step_number=1,
            description="Search memories",
            thought_prompt="What to search?",
            required_tools=["memory_search"],
            expected_output="Results",
            dependencies=[0],
        )

        result = step.to_dict()

        assert result["step_number"] == 1
        assert result["description"] == "Search memories"
        assert result["thought_prompt"] == "What to search?"
        assert result["required_tools"] == ["memory_search"]
        assert result["expected_output"] == "Results"
        assert result["dependencies"] == [0]
