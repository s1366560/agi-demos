"""
ReflectionResult domain model for Plan Mode.

Defines the result of reflection analysis on plan execution.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict


class AdjustmentType(str, Enum):
    """Type of adjustment to make to a step."""

    MODIFY = "modify"
    RETRY = "retry"
    SKIP = "skip"
    ADD_BEFORE = "add_before"
    ADD_AFTER = "add_after"
    REPLACE = "replace"


class ReflectionAssessment(str, Enum):
    """Assessment of plan execution progress."""

    ON_TRACK = "on_track"
    NEEDS_ADJUSTMENT = "needs_adjustment"
    OFF_TRACK = "off_track"
    COMPLETE = "complete"
    FAILED = "failed"


@dataclass(frozen=True)
class StepAdjustment:
    """
    An adjustment to make to a step in the execution plan.

    Attributes:
        step_id: ID of the step to adjust
        adjustment_type: Type of adjustment to make
        reason: Human-readable explanation for the adjustment
        new_tool_input: New input parameters (for MODIFY)
        new_tool_name: New tool name (for REPLACE)
        new_step: New step instance (for ADD_BEFORE, ADD_AFTER, REPLACE)
    """

    step_id: str
    adjustment_type: AdjustmentType
    reason: str
    new_tool_input: Dict[str, Any] | None = None
    new_tool_name: str | None = None
    new_step: Any | None = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "step_id": self.step_id,
            "adjustment_type": self.adjustment_type.value,
            "reason": self.reason,
            "new_tool_input": self.new_tool_input,
            "new_tool_name": self.new_tool_name,
            "new_step": self.new_step.to_dict() if hasattr(self.new_step, "to_dict") else self.new_step,
        }


@dataclass(frozen=True)
class ReflectionResult:
    """
    Result of reflecting on plan execution.

    Produced by PlanReflector after evaluating progress and determining
    if any adjustments are needed.

    Attributes:
        assessment: Overall assessment of execution progress
        reasoning: Human-readable explanation of the assessment
        adjustments: List of adjustments to apply
        suggested_next_steps: Optional suggested next steps
        confidence: Confidence level in the assessment (0-1)
        final_summary: Summary when assessment is COMPLETE
        error_type: Type of error when assessment is FAILED
        reflection_metadata: Additional metadata about the reflection
    """

    assessment: ReflectionAssessment
    reasoning: str
    adjustments: list[StepAdjustment] = field(default_factory=list)
    suggested_next_steps: list[str] | None = None
    confidence: float | None = None
    final_summary: str | None = None
    error_type: str | None = None
    reflection_metadata: Dict[str, Any] = field(default_factory=dict)

    def has_adjustments(self) -> bool:
        """Check if there are any adjustments to apply."""
        return len(self.adjustments) > 0

    def get_adjustments_for_step(self, step_id: str) -> list[StepAdjustment]:
        """Get all adjustments for a specific step."""
        return [a for a in self.adjustments if a.step_id == step_id]

    @property
    def is_terminal(self) -> bool:
        """Check if this reflection represents a terminal state."""
        return self.assessment in (ReflectionAssessment.COMPLETE, ReflectionAssessment.FAILED)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "assessment": self.assessment.value,
            "reasoning": self.reasoning,
            "adjustments": [a.to_dict() for a in self.adjustments],
            "suggested_next_steps": self.suggested_next_steps,
            "confidence": self.confidence,
            "final_summary": self.final_summary,
            "error_type": self.error_type,
            "reflection_metadata": self.reflection_metadata,
        }

    @classmethod
    def on_track(
        cls,
        reasoning: str,
        confidence: float | None = None,
    ) -> "ReflectionResult":
        """Create a reflection indicating execution is on track."""
        return cls(
            assessment=ReflectionAssessment.ON_TRACK,
            reasoning=reasoning,
            confidence=confidence,
        )

    @classmethod
    def needs_adjustment(
        cls,
        reasoning: str,
        adjustments: list[StepAdjustment],
        confidence: float | None = None,
    ) -> "ReflectionResult":
        """Create a reflection indicating adjustments are needed."""
        return cls(
            assessment=ReflectionAssessment.NEEDS_ADJUSTMENT,
            reasoning=reasoning,
            adjustments=adjustments,
            confidence=confidence,
        )

    @classmethod
    def complete(
        cls,
        reasoning: str,
        final_summary: str | None = None,
    ) -> "ReflectionResult":
        """Create a reflection indicating plan is complete."""
        return cls(
            assessment=ReflectionAssessment.COMPLETE,
            reasoning=reasoning,
            final_summary=final_summary,
        )

    @classmethod
    def failed(
        cls,
        reasoning: str,
        error_type: str | None = None,
    ) -> "ReflectionResult":
        """Create a reflection indicating plan has failed."""
        return cls(
            assessment=ReflectionAssessment.FAILED,
            reasoning=reasoning,
            error_type=error_type,
        )

    @classmethod
    def off_track(
        cls,
        reasoning: str,
        suggested_next_steps: list[str] | None = None,
    ) -> "ReflectionResult":
        """Create a reflection indicating execution is off track."""
        return cls(
            assessment=ReflectionAssessment.OFF_TRACK,
            reasoning=reasoning,
            suggested_next_steps=suggested_next_steps,
        )
