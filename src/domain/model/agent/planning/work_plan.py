"""WorkPlan entity for multi-level thinking support."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict

from src.domain.model.agent.planning.plan_status import PlanStatus
from src.domain.model.agent.planning.plan_step import PlanStep
from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class WorkPlan(Entity):
    """
    A work-level plan for executing a complex query.

    The work plan represents the high-level planning that the agent does
    before executing individual steps. Each step will have its own
    task-level thinking.
    """

    conversation_id: str
    status: PlanStatus
    steps: list[PlanStep]
    current_step_index: int = 0
    completed_step_indices: list[int] = field(default_factory=list)  # Track completed steps
    workflow_pattern_id: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime | None = None

    def get_current_step(self) -> PlanStep | None:
        """Get the current step being executed."""
        if 0 <= self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    def get_next_step(self) -> PlanStep | None:
        """Get the next step to execute."""
        next_index = self.current_step_index + 1
        if next_index < len(self.steps):
            return self.steps[next_index]
        return None

    def advance_step(self) -> None:
        """Move to the next step (also marks current step as completed)."""
        self.complete_current_step()
        if self.current_step_index + 1 < len(self.steps):
            self.current_step_index += 1
            self.updated_at = datetime.utcnow()

    def complete_current_step(self) -> None:
        """Mark the current step as completed."""
        if self.current_step_index not in self.completed_step_indices:
            self.completed_step_indices.append(self.current_step_index)
            self.updated_at = datetime.utcnow()

    def mark_in_progress(self) -> None:
        """Mark the plan as in progress."""
        self.status = PlanStatus.IN_PROGRESS
        self.updated_at = datetime.utcnow()

    def mark_completed(self) -> None:
        """Mark the plan as completed."""
        self.status = PlanStatus.COMPLETED
        self.updated_at = datetime.utcnow()

    def mark_failed(self) -> None:
        """Mark the plan as failed."""
        self.status = PlanStatus.FAILED
        self.updated_at = datetime.utcnow()

    @property
    def is_complete(self) -> bool:
        """Check if all steps are completed."""
        if not self.steps:
            return True
        return len(self.completed_step_indices) == len(self.steps)

    @property
    def progress_percentage(self) -> float:
        """Get the progress percentage of the plan based on completed steps."""
        if not self.steps:
            return 100.0
        return len(self.completed_step_indices) / len(self.steps) * 100

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "status": self.status.value,
            "steps": [step.to_dict() for step in self.steps],
            "current_step_index": self.current_step_index,
            "completed_step_indices": list(self.completed_step_indices),
            "workflow_pattern_id": self.workflow_pattern_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
