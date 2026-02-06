"""Step result for tracking execution outcomes."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from src.domain.shared_kernel import ValueObject


class StepOutcome(str, Enum):
    """Outcome of a step execution."""

    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"
    TIMEOUT = "timeout"
    ABORTED = "aborted"


@dataclass(frozen=True)
class StepResult(ValueObject):
    """
    Result of executing a single step.

    Captures:
    - Execution outcome
    - Output data
    - Error information
    - Timing information
    """

    step_id: str
    outcome: StepOutcome
    output: Optional[str] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    duration_ms: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    executed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def is_success(self) -> bool:
        """Check if step executed successfully."""
        return self.outcome == StepOutcome.SUCCESS

    def is_failure(self) -> bool:
        """Check if step execution failed."""
        return self.outcome in (StepOutcome.FAILURE, StepOutcome.TIMEOUT, StepOutcome.ABORTED)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "step_id": self.step_id,
            "outcome": self.outcome.value,
            "output": self.output,
            "error": self.error,
            "error_code": self.error_code,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
            "executed_at": self.executed_at.isoformat(),
        }

    @classmethod
    def success(cls, step_id: str, output: str, duration_ms: int = 0) -> "StepResult":
        """Create a successful step result."""
        return cls(
            step_id=step_id,
            outcome=StepOutcome.SUCCESS,
            output=output,
            duration_ms=duration_ms,
        )

    @classmethod
    def failure(cls, step_id: str, error: str, error_code: Optional[str] = None) -> "StepResult":
        """Create a failed step result."""
        return cls(
            step_id=step_id,
            outcome=StepOutcome.FAILURE,
            error=error,
            error_code=error_code,
        )
