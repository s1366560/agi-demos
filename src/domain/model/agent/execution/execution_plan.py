"""
ExecutionPlan domain model for Plan Mode.

Defines the execution plan entity and its component steps.
This model represents a pre-generated plan for complex query execution.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict

from src.domain.shared_kernel import Entity


class ExecutionStepStatus(str, Enum):
    """Status of a single execution step."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ExecutionPlanStatus(str, Enum):
    """Status of the overall execution plan."""

    DRAFT = "draft"
    APPROVED = "approved"
    EXECUTING = "executing"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ExecutionStep:
    """
    A single step in an execution plan.

    Attributes:
        step_id: Unique identifier for this step
        description: Human-readable description of what this step does
        tool_name: Name of the tool to execute
        tool_input: Input parameters for the tool
        dependencies: List of step_ids that must complete before this step
        status: Current execution status
        result: Output from tool execution (when completed)
        error: Error message (when failed)
        started_at: When step execution started
        completed_at: When step execution completed/failed
    """

    step_id: str
    description: str
    tool_name: str
    tool_input: Dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    status: ExecutionStepStatus = ExecutionStepStatus.PENDING
    result: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def mark_started(self) -> "ExecutionStep":
        """Mark step as started. Returns new instance."""
        return replace(
            self, status=ExecutionStepStatus.RUNNING, started_at=datetime.now(timezone.utc)
        )

    def mark_completed(self, result: str) -> "ExecutionStep":
        """Mark step as completed with result. Returns new instance."""
        return replace(
            self,
            status=ExecutionStepStatus.COMPLETED,
            result=result,
            completed_at=datetime.now(timezone.utc),
        )

    def mark_failed(self, error: str) -> "ExecutionStep":
        """Mark step as failed. Returns new instance."""
        return replace(
            self,
            status=ExecutionStepStatus.FAILED,
            error=error,
            completed_at=datetime.now(timezone.utc),
        )

    def mark_skipped(self, reason: str) -> "ExecutionStep":
        """Mark step as skipped. Returns new instance."""
        return replace(
            self,
            status=ExecutionStepStatus.SKIPPED,
            error=reason,
            completed_at=datetime.now(timezone.utc),
        )

    def is_ready(self, completed_steps: set[str]) -> bool:
        """Check if step is ready to execute (all dependencies met)."""
        if self.status != ExecutionStepStatus.PENDING:
            return False
        return all(dep in completed_steps for dep in self.dependencies)

    def to_dict(self) -> Dict[str, Any]:
        """Convert step to dictionary for serialization."""
        return {
            "step_id": self.step_id,
            "description": self.description,
            "tool_name": self.tool_name,
            "tool_input": self.tool_input,
            "dependencies": list(self.dependencies),
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


@dataclass(kw_only=True)
class ExecutionPlan(Entity):
    """
    An execution plan for complex query processing.

    The ExecutionPlan represents a pre-generated sequence of steps to achieve
    a goal. It supports reflection and rollback capabilities.

    Attributes:
        conversation_id: Associated conversation
        user_query: Original user query that triggered this plan
        steps: Ordered list of execution steps
        status: Current plan status
        reflection_enabled: Whether automatic reflection is enabled
        max_reflection_cycles: Maximum number of reflection cycles
        completed_steps: List of step IDs that completed successfully
        failed_steps: List of step IDs that failed
        snapshot: Optional snapshot for rollback
        started_at: When plan execution started
        completed_at: When plan execution completed/failed
        error: Error message (when plan failed)
    """

    conversation_id: str
    user_query: str
    steps: list[ExecutionStep]
    status: ExecutionPlanStatus = ExecutionPlanStatus.DRAFT
    reflection_enabled: bool = True
    max_reflection_cycles: int = 3
    completed_steps: list[str] = field(default_factory=list)
    failed_steps: list[str] = field(default_factory=list)
    snapshot: Any | None = None  # PlanSnapshot type, forward reference
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None

    def get_ready_steps(self) -> list[str]:
        """
        Get list of step IDs ready to execute.

        A step is ready when:
        - It is PENDING status
        - All its dependencies are in completed_steps
        """
        ready: list[str] = []
        completed_set = set(self.completed_steps)

        for step in self.steps:
            if step.is_ready(completed_set):
                ready.append(step.step_id)

        return ready

    def update_step(self, updated_step: ExecutionStep) -> "ExecutionPlan":
        """Update a step in the plan. Returns new plan instance."""
        new_steps = []
        for step in self.steps:
            if step.step_id == updated_step.step_id:
                new_steps.append(updated_step)
            else:
                new_steps.append(step)

        return replace(self, steps=new_steps)

    def mark_step_completed(self, step_id: str, result: str) -> "ExecutionPlan":
        """Mark a step as completed. Returns new plan instance."""
        new_completed = list(self.completed_steps)
        if step_id not in new_completed:
            new_completed.append(step_id)

        # Find and update the step
        new_steps = []
        for step in self.steps:
            if step.step_id == step_id:
                new_steps.append(step.mark_completed(result))
            else:
                new_steps.append(step)

        return replace(self, steps=new_steps, completed_steps=new_completed)

    def mark_step_failed(self, step_id: str, error: str) -> "ExecutionPlan":
        """Mark a step as failed. Returns new plan instance."""
        new_failed = list(self.failed_steps)
        if step_id not in new_failed:
            new_failed.append(step_id)

        # Find and update the step
        new_steps = []
        for step in self.steps:
            if step.step_id == step_id:
                new_steps.append(step.mark_failed(error))
            else:
                new_steps.append(step)

        return replace(self, steps=new_steps, failed_steps=new_failed)

    def mark_step_started(self, step_id: str) -> "ExecutionPlan":
        """Mark a step as started. Returns new plan instance."""
        new_steps = []
        for step in self.steps:
            if step.step_id == step_id:
                new_steps.append(step.mark_started())
            else:
                new_steps.append(step)

        return replace(self, steps=new_steps)

    def mark_executing(self) -> "ExecutionPlan":
        """Mark plan as executing. Returns new plan instance."""
        return replace(
            self, status=ExecutionPlanStatus.EXECUTING, started_at=datetime.now(timezone.utc)
        )

    def mark_completed(self) -> "ExecutionPlan":
        """Mark plan as completed. Returns new plan instance."""
        return replace(
            self,
            status=ExecutionPlanStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc),
        )

    def mark_failed(self, error: str) -> "ExecutionPlan":
        """Mark plan as failed. Returns new plan instance."""
        return replace(
            self,
            status=ExecutionPlanStatus.FAILED,
            error=error,
            completed_at=datetime.now(timezone.utc),
        )

    def mark_cancelled(self) -> "ExecutionPlan":
        """Mark plan as cancelled. Returns new plan instance."""
        return replace(
            self,
            status=ExecutionPlanStatus.CANCELLED,
            completed_at=datetime.now(timezone.utc),
        )

    @property
    def is_complete(self) -> bool:
        """Check if plan is complete (all steps done or no steps)."""
        if not self.steps:
            return True

        total_steps = len(self.steps)
        done_steps = len(self.completed_steps) + len(self.failed_steps)

        return done_steps >= total_steps

    @property
    def progress_percentage(self) -> float:
        """Get progress percentage (completed + failed) / total."""
        if not self.steps:
            return 100.0

        total = len(self.steps)
        done = len(self.completed_steps) + len(self.failed_steps)

        return (done / total) * 100.0

    def get_step_by_id(self, step_id: str) -> ExecutionStep | None:
        """Get a step by its ID."""
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None

    def create_snapshot(self, name: str, description: str | None = None) -> Any:
        """Create a snapshot of current plan state for rollback."""
        from src.domain.model.agent.planning.plan_snapshot import PlanSnapshot, StepState

        step_states: dict[str, StepState] = {}
        for step in self.steps:
            step_states[step.step_id] = StepState.from_execution_step(step)

        return PlanSnapshot(
            plan_id=self.id,
            name=name,
            step_states=step_states,
            description=description,
            auto_created=True,
            snapshot_type="last_step",
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert plan to dictionary for serialization."""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "user_query": self.user_query,
            "steps": [step.to_dict() for step in self.steps],
            "status": self.status.value,
            "reflection_enabled": self.reflection_enabled,
            "max_reflection_cycles": self.max_reflection_cycles,
            "completed_steps": list(self.completed_steps),
            "failed_steps": list(self.failed_steps),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error": self.error,
        }
