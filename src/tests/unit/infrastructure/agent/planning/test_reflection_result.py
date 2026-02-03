"""
Unit tests for ReflectionResult domain model.

Tests follow TDD: Write first, verify FAIL, implement, verify PASS.
"""


import pytest

from src.domain.model.agent.reflection_result import (
    AdjustmentType,
    ReflectionAssessment,
    ReflectionResult,
    StepAdjustment,
)


class TestAdjustmentType:
    """Tests for AdjustmentType enum."""

    def test_adjustment_type_values(self) -> None:
        """Test that adjustment type enum has all expected values."""
        assert AdjustmentType.MODIFY.value == "modify"
        assert AdjustmentType.RETRY.value == "retry"
        assert AdjustmentType.SKIP.value == "skip"
        assert AdjustmentType.ADD_BEFORE.value == "add_before"
        assert AdjustmentType.ADD_AFTER.value == "add_after"
        assert AdjustmentType.REPLACE.value == "replace"


class TestStepAdjustment:
    """Tests for StepAdjustment value object."""

    def test_create_modify_adjustment(self) -> None:
        """Test creating a modify adjustment."""
        adjustment = StepAdjustment(
            step_id="step-1",
            adjustment_type=AdjustmentType.MODIFY,
            reason="Tool input was incorrect",
            new_tool_input={"query": "corrected query"},
        )

        assert adjustment.step_id == "step-1"
        assert adjustment.adjustment_type == AdjustmentType.MODIFY
        assert adjustment.reason == "Tool input was incorrect"
        assert adjustment.new_tool_input == {"query": "corrected query"}
        assert adjustment.new_tool_name is None

    def test_create_retry_adjustment(self) -> None:
        """Test creating a retry adjustment."""
        adjustment = StepAdjustment(
            step_id="step-2",
            adjustment_type=AdjustmentType.RETRY,
            reason="Transient network error",
        )

        assert adjustment.adjustment_type == AdjustmentType.RETRY
        assert adjustment.reason == "Transient network error"

    def test_create_skip_adjustment(self) -> None:
        """Test creating a skip adjustment."""
        adjustment = StepAdjustment(
            step_id="step-3",
            adjustment_type=AdjustmentType.SKIP,
            reason="Information already available",
        )

        assert adjustment.adjustment_type == AdjustmentType.SKIP

    def test_create_add_before_adjustment(self) -> None:
        """Test creating an add_before adjustment."""
        from src.domain.model.agent.execution_plan import ExecutionStep

        new_step = ExecutionStep(
            step_id="step-new",
            description="Preprocessing step",
            tool_name="Preprocessor",
        )
        adjustment = StepAdjustment(
            step_id="step-2",
            adjustment_type=AdjustmentType.ADD_BEFORE,
            reason="Need to validate input first",
            new_step=new_step,
        )

        assert adjustment.adjustment_type == AdjustmentType.ADD_BEFORE
        assert adjustment.new_step == new_step

    def test_create_add_after_adjustment(self) -> None:
        """Test creating an add_after adjustment."""
        from src.domain.model.agent.execution_plan import ExecutionStep

        new_step = ExecutionStep(
            step_id="step-new",
            description="Post-processing step",
            tool_name="Postprocessor",
        )
        adjustment = StepAdjustment(
            step_id="step-1",
            adjustment_type=AdjustmentType.ADD_AFTER,
            reason="Need to format output",
            new_step=new_step,
        )

        assert adjustment.adjustment_type == AdjustmentType.ADD_AFTER
        assert adjustment.new_step == new_step

    def test_create_replace_adjustment(self) -> None:
        """Test creating a replace adjustment."""
        from src.domain.model.agent.execution_plan import ExecutionStep

        new_step = ExecutionStep(
            step_id="step-replacement",
            description="Better approach",
            tool_name="BetterTool",
        )
        adjustment = StepAdjustment(
            step_id="step-old",
            adjustment_type=AdjustmentType.REPLACE,
            reason="Original tool insufficient",
            new_step=new_step,
        )

        assert adjustment.adjustment_type == AdjustmentType.REPLACE
        assert adjustment.new_step == new_step

    def test_step_adjustment_is_immutable(self) -> None:
        """Test that StepAdjustment is immutable."""
        from dataclasses import FrozenInstanceError

        adjustment = StepAdjustment(
            step_id="step-1",
            adjustment_type=AdjustmentType.MODIFY,
            reason="Test",
        )

        with pytest.raises(FrozenInstanceError):
            adjustment.reason = "Modified"

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        adjustment = StepAdjustment(
            step_id="step-1",
            adjustment_type=AdjustmentType.MODIFY,
            reason="Fix input",
            new_tool_input={"fixed": True},
        )

        result = adjustment.to_dict()

        assert result["step_id"] == "step-1"
        assert result["adjustment_type"] == "modify"
        assert result["reason"] == "Fix input"
        assert result["new_tool_input"] == {"fixed": True}


class TestReflectionAssessment:
    """Tests for ReflectionAssessment enum."""

    def test_assessment_values(self) -> None:
        """Test that assessment enum has all expected values."""
        assert ReflectionAssessment.ON_TRACK.value == "on_track"
        assert ReflectionAssessment.NEEDS_ADJUSTMENT.value == "needs_adjustment"
        assert ReflectionAssessment.OFF_TRACK.value == "off_track"
        assert ReflectionAssessment.COMPLETE.value == "complete"
        assert ReflectionAssessment.FAILED.value == "failed"


class TestReflectionResult:
    """Tests for ReflectionResult value object."""

    def test_create_reflection_result_minimal(self) -> None:
        """Test creating a reflection result with minimal fields."""
        result = ReflectionResult(
            assessment=ReflectionAssessment.ON_TRACK,
            reasoning="Everything proceeding as expected",
        )

        assert result.assessment == ReflectionAssessment.ON_TRACK
        assert result.reasoning == "Everything proceeding as expected"
        assert result.adjustments == []
        assert result.suggested_next_steps is None
        assert result.confidence is None

    def test_create_reflection_result_with_adjustments(self) -> None:
        """Test creating reflection with adjustments."""
        adjustment = StepAdjustment(
            step_id="step-1",
            adjustment_type=AdjustmentType.MODIFY,
            reason="Fix input",
            new_tool_input={"corrected": True},
        )
        result = ReflectionResult(
            assessment=ReflectionAssessment.NEEDS_ADJUSTMENT,
            reasoning="Step 1 needs modification",
            adjustments=[adjustment],
            confidence=0.8,
        )

        assert result.assessment == ReflectionAssessment.NEEDS_ADJUSTMENT
        assert len(result.adjustments) == 1
        assert result.adjustments[0].step_id == "step-1"
        assert result.confidence == 0.8

    def test_create_reflection_result_full(self) -> None:
        """Test creating reflection with all fields."""
        adjustment1 = StepAdjustment(
            step_id="step-1",
            adjustment_type=AdjustmentType.MODIFY,
            reason="Fix",
        )
        adjustment2 = StepAdjustment(
            step_id="step-2",
            adjustment_type=AdjustmentType.RETRY,
            reason="Retry",
        )
        result = ReflectionResult(
            assessment=ReflectionAssessment.NEEDS_ADJUSTMENT,
            reasoning="Multiple issues found",
            adjustments=[adjustment1, adjustment2],
            suggested_next_steps=["Retry step 2", "Verify output"],
            confidence=0.9,
            reflection_metadata={"model": "gpt-4", "tokens": 100},
        )

        assert len(result.adjustments) == 2
        assert result.suggested_next_steps == ["Retry step 2", "Verify output"]
        assert result.confidence == 0.9
        assert result.reflection_metadata == {"model": "gpt-4", "tokens": 100}

    def test_has_adjustments(self) -> None:
        """Test checking if reflection has adjustments."""
        result_empty = ReflectionResult(
            assessment=ReflectionAssessment.ON_TRACK,
            reasoning="No changes needed",
        )

        adjustment = StepAdjustment(
            step_id="step-1",
            adjustment_type=AdjustmentType.MODIFY,
            reason="Fix",
        )
        result_with_adj = ReflectionResult(
            assessment=ReflectionAssessment.NEEDS_ADJUSTMENT,
            reasoning="Need changes",
            adjustments=[adjustment],
        )

        assert result_empty.has_adjustments() is False  # Call the method
        assert result_with_adj.has_adjustments() is True  # Call the method

    def test_get_adjustments_for_step(self) -> None:
        """Test getting adjustments for a specific step."""
        adj1 = StepAdjustment(
            step_id="step-1",
            adjustment_type=AdjustmentType.MODIFY,
            reason="Fix 1",
        )
        adj2 = StepAdjustment(
            step_id="step-2",
            adjustment_type=AdjustmentType.RETRY,
            reason="Fix 2",
        )
        result = ReflectionResult(
            assessment=ReflectionAssessment.NEEDS_ADJUSTMENT,
            reasoning="Multiple fixes",
            adjustments=[adj1, adj2],
        )

        assert result.get_adjustments_for_step("step-1") == [adj1]
        assert result.get_adjustments_for_step("step-2") == [adj2]
        assert result.get_adjustments_for_step("step-3") == []

    def test_is_terminal(self) -> None:
        """Test checking if reflection represents a terminal state."""
        on_track = ReflectionResult(
            assessment=ReflectionAssessment.ON_TRACK,
            reasoning="Continue",
        )
        complete = ReflectionResult(
            assessment=ReflectionAssessment.COMPLETE,
            reasoning="Done",
        )
        failed = ReflectionResult(
            assessment=ReflectionAssessment.FAILED,
            reasoning="Cannot proceed",
        )

        assert on_track.is_terminal is False
        assert complete.is_terminal is True
        assert failed.is_terminal is True

    def test_to_dict(self) -> None:
        """Test serialization to dictionary."""
        adjustment = StepAdjustment(
            step_id="step-1",
            adjustment_type=AdjustmentType.MODIFY,
            reason="Fix",
        )
        result = ReflectionResult(
            assessment=ReflectionAssessment.NEEDS_ADJUSTMENT,
            reasoning="Need changes",
            adjustments=[adjustment],
            confidence=0.85,
        )

        dict_result = result.to_dict()

        assert dict_result["assessment"] == "needs_adjustment"
        assert dict_result["reasoning"] == "Need changes"
        assert len(dict_result["adjustments"]) == 1
        assert dict_result["confidence"] == 0.85

    def test_create_on_track(self) -> None:
        """Test factory method for on_track assessment."""
        result = ReflectionResult.on_track(
            reasoning="Proceeding normally",
            confidence=0.9,
        )

        assert result.assessment == ReflectionAssessment.ON_TRACK
        assert result.reasoning == "Proceeding normally"
        assert result.confidence == 0.9
        assert result.adjustments == []

    def test_create_needs_adjustment(self) -> None:
        """Test factory method for needs_adjustment assessment."""
        adjustment = StepAdjustment(
            step_id="step-1",
            adjustment_type=AdjustmentType.MODIFY,
            reason="Fix",
        )
        result = ReflectionResult.needs_adjustment(
            reasoning="Fix required",
            adjustments=[adjustment],
        )

        assert result.assessment == ReflectionAssessment.NEEDS_ADJUSTMENT
        assert result.adjustments == [adjustment]

    def test_create_complete(self) -> None:
        """Test factory method for complete assessment."""
        result = ReflectionResult.complete(
            reasoning="Goal achieved",
            final_summary="All done",
        )

        assert result.assessment == ReflectionAssessment.COMPLETE
        assert result.reasoning == "Goal achieved"
        assert result.final_summary == "All done"

    def test_create_failed(self) -> None:
        """Test factory method for failed assessment."""
        result = ReflectionResult.failed(
            reasoning="Cannot continue",
            error_type="validation_error",
        )

        assert result.assessment == ReflectionAssessment.FAILED
        assert result.reasoning == "Cannot continue"
        assert result.error_type == "validation_error"

    def test_create_off_track(self) -> None:
        """Test factory method for off_track assessment."""
        result = ReflectionResult.off_track(
            reasoning="Deviated from plan",
            suggested_next_steps=["Realign", "Verify"],
        )

        assert result.assessment == ReflectionAssessment.OFF_TRACK
        assert result.suggested_next_steps == ["Realign", "Verify"]
