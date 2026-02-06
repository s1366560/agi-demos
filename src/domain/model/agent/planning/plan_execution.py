"""PlanExecution domain model for unified plan execution.

This module defines the PlanExecution entity that merges WorkPlan and ExecutionPlan
into a unified model for both multi-level thinking and Plan Mode execution.
"""

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from src.domain.shared_kernel import Entity


class ExecutionStatus(str, Enum):
    """Status of plan execution."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"  # Support pause/resume
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionMode(str, Enum):
    """Execution mode for plan steps."""

    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


class StepStatus(str, Enum):
    """Status of a single execution step."""

    PENDING = "pending"
    READY = "ready"  # Dependencies met, ready to execute
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ExecutionStep:
    """
    A single step in a plan execution.

    Merges PlanStep and ExecutionStep into a unified step definition.

    Attributes:
        step_id: Unique identifier for this step
        step_number: Sequential number for ordering and display
        description: Human-readable description
        thought_prompt: Task-level thinking prompt
        expected_output: Expected output description
        tool_name: Name of the tool to execute
        tool_input: Input parameters for the tool
        dependencies: List of step_ids that must complete before this step
        status: Current execution status
        result: Output from tool execution (when completed)
        error: Error message (when failed)
        started_at: When step execution started
        completed_at: When step execution completed/failed
        execution_time_ms: Execution time in milliseconds
        retry_count: Number of retries
    """

    step_id: str
    step_number: int
    description: str
    thought_prompt: str
    expected_output: str
    tool_name: str
    tool_input: Dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    status: StepStatus = StepStatus.PENDING
    result: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    execution_time_ms: int = 0
    retry_count: int = 0

    def mark_started(self) -> "ExecutionStep":
        """Mark step as started. Returns new instance."""
        return replace(
            self,
            status=StepStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
        )

    def mark_completed(self, result: str) -> "ExecutionStep":
        """Mark step as completed with result. Returns new instance."""
        now = datetime.now(timezone.utc)
        execution_time = 0
        if self.started_at:
            execution_time = int((now - self.started_at).total_seconds() * 1000)
        return replace(
            self,
            status=StepStatus.COMPLETED,
            result=result,
            completed_at=now,
            execution_time_ms=execution_time,
        )

    def mark_failed(self, error: str) -> "ExecutionStep":
        """Mark step as failed. Returns new instance."""
        now = datetime.now(timezone.utc)
        execution_time = 0
        if self.started_at:
            execution_time = int((now - self.started_at).total_seconds() * 1000)
        return replace(
            self,
            status=StepStatus.FAILED,
            error=error,
            completed_at=now,
            execution_time_ms=execution_time,
        )

    def mark_skipped(self, reason: str) -> "ExecutionStep":
        """Mark step as skipped. Returns new instance."""
        return replace(
            self,
            status=StepStatus.SKIPPED,
            error=reason,
            completed_at=datetime.now(timezone.utc),
        )

    def is_ready(self, completed_steps: set[str]) -> bool:
        """Check if step is ready to execute (all dependencies met)."""
        if self.status != StepStatus.PENDING:
            return False
        return all(dep in completed_steps for dep in self.dependencies)

    def to_dict(self) -> Dict[str, Any]:
        """Convert step to dictionary for serialization."""
        return {
            "step_id": self.step_id,
            "step_number": self.step_number,
            "description": self.description,
            "thought_prompt": self.thought_prompt,
            "expected_output": self.expected_output,
            "tool_name": self.tool_name,
            "tool_input": dict(self.tool_input),
            "dependencies": list(self.dependencies),
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "execution_time_ms": self.execution_time_ms,
            "retry_count": self.retry_count,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionStep":
        """Create ExecutionStep from dictionary."""
        return cls(
            step_id=data["step_id"],
            step_number=data["step_number"],
            description=data["description"],
            thought_prompt=data["thought_prompt"],
            expected_output=data["expected_output"],
            tool_name=data["tool_name"],
            tool_input=data.get("tool_input", {}),
            dependencies=data.get("dependencies", []),
            status=StepStatus(data.get("status", "pending")),
            result=data.get("result"),
            error=data.get("error"),
            started_at=datetime.fromisoformat(data["started_at"])
            if data.get("started_at")
            else None,
            completed_at=datetime.fromisoformat(data["completed_at"])
            if data.get("completed_at")
            else None,
            execution_time_ms=data.get("execution_time_ms", 0),
            retry_count=data.get("retry_count", 0),
        )


@dataclass(kw_only=True)
class PlanExecution(Entity):
    """
    Unified execution plan entity.

    Merges WorkPlan and ExecutionPlan into a single model that serves both:
    1. Multi-level thinking workflow
    2. Plan Mode execution

    Attributes:
        conversation_id: Associated conversation
        plan_id: Optional link to Plan document (for Plan Mode)
        steps: Ordered list of execution steps
        current_step_index: Index of current step being executed
        completed_step_indices: List of completed step indices
        failed_step_indices: List of failed step indices
        status: Current execution status
        execution_mode: Sequential or parallel execution
        max_parallel_steps: Maximum parallel steps when in parallel mode
        reflection_enabled: Whether automatic reflection is enabled
        max_reflection_cycles: Maximum number of reflection cycles
        current_reflection_cycle: Current reflection cycle count
        workflow_pattern_id: Optional workflow pattern for multi-level thinking
        metadata: Additional metadata
        created_at: Creation timestamp
        updated_at: Last update timestamp
        started_at: Execution start timestamp
        completed_at: Execution completion timestamp
    """

    conversation_id: str
    plan_id: Optional[str] = None  # Link to Plan document (for Plan Mode)

    # Steps
    steps: list[ExecutionStep] = field(default_factory=list)
    current_step_index: int = 0
    completed_step_indices: list[int] = field(default_factory=list)
    failed_step_indices: list[int] = field(default_factory=list)

    # Status
    status: ExecutionStatus = ExecutionStatus.PENDING

    # Execution config
    execution_mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    max_parallel_steps: int = 3

    # Reflection config
    reflection_enabled: bool = True
    max_reflection_cycles: int = 3
    current_reflection_cycle: int = 0

    # Metadata
    workflow_pattern_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Timestamps
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    def get_step_by_id(self, step_id: str) -> Optional[ExecutionStep]:
        """Get a step by its ID."""
        for step in self.steps:
            if step.step_id == step_id:
                return step
        return None

    def get_step_by_number(self, step_number: int) -> Optional[ExecutionStep]:
        """Get a step by its number."""
        for step in self.steps:
            if step.step_number == step_number:
                return step
        return None

    def get_current_step(self) -> Optional[ExecutionStep]:
        """Get the current step being executed."""
        return self.get_step_by_number(self.current_step_index)

    def get_next_step(self) -> Optional[ExecutionStep]:
        """Get the next step to execute."""
        next_number = self.current_step_index + 1
        return self.get_step_by_number(next_number)

    def get_ready_steps(self) -> list[str]:
        """Get list of step IDs ready to execute."""
        ready: list[str] = []
        completed_set = {self.steps[i].step_id for i in self.completed_step_indices}

        for step in self.steps:
            if step.is_ready(completed_set):
                ready.append(step.step_id)

        return ready

    def update_step(self, updated_step: ExecutionStep) -> "PlanExecution":
        """Update a step in the plan. Returns new instance."""
        new_steps = []
        for step in self.steps:
            if step.step_id == updated_step.step_id:
                new_steps.append(updated_step)
            else:
                new_steps.append(step)

        return replace(
            self,
            steps=new_steps,
            updated_at=datetime.now(timezone.utc),
        )

    def mark_step_started(self, step_id: str) -> "PlanExecution":
        """Mark a step as started. Returns new instance."""
        step = self.get_step_by_id(step_id)
        if step:
            updated_step = step.mark_started()
            return self.update_step(updated_step)
        return self

    def mark_step_completed(self, step_id: str, result: str) -> "PlanExecution":
        """Mark a step as completed. Returns new instance."""
        step = self.get_step_by_id(step_id)
        if not step:
            return self

        # Find step index
        step_index = None
        for i, s in enumerate(self.steps):
            if s.step_id == step_id:
                step_index = i
                break

        updated_step = step.mark_completed(result)
        new_completed = list(self.completed_step_indices)
        if step_index is not None and step_index not in new_completed:
            new_completed.append(step_index)

        return replace(
            self,
            steps=[updated_step if s.step_id == step_id else s for s in self.steps],
            completed_step_indices=new_completed,
            updated_at=datetime.now(timezone.utc),
        )

    def mark_step_failed(self, step_id: str, error: str) -> "PlanExecution":
        """Mark a step as failed. Returns new instance."""
        step = self.get_step_by_id(step_id)
        if not step:
            return self

        # Find step index
        step_index = None
        for i, s in enumerate(self.steps):
            if s.step_id == step_id:
                step_index = i
                break

        updated_step = step.mark_failed(error)
        new_failed = list(self.failed_step_indices)
        if step_index is not None and step_index not in new_failed:
            new_failed.append(step_index)

        return replace(
            self,
            steps=[updated_step if s.step_id == step_id else s for s in self.steps],
            failed_step_indices=new_failed,
            updated_at=datetime.now(timezone.utc),
        )

    def advance_step(self) -> "PlanExecution":
        """Move to the next step. Returns new instance."""
        next_index = self.current_step_index + 1
        if next_index < len(self.steps):
            return replace(
                self,
                current_step_index=next_index,
                updated_at=datetime.now(timezone.utc),
            )
        return self

    def mark_running(self) -> "PlanExecution":
        """Mark execution as running. Returns new instance."""
        return replace(
            self,
            status=ExecutionStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    def mark_paused(self) -> "PlanExecution":
        """Mark execution as paused. Returns new instance."""
        return replace(
            self,
            status=ExecutionStatus.PAUSED,
            updated_at=datetime.now(timezone.utc),
        )

    def mark_completed(self) -> "PlanExecution":
        """Mark execution as completed. Returns new instance."""
        return replace(
            self,
            status=ExecutionStatus.COMPLETED,
            completed_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    def mark_failed(self, error: str) -> "PlanExecution":
        """Mark execution as failed. Returns new instance."""
        metadata = dict(self.metadata)
        metadata["error"] = error
        return replace(
            self,
            status=ExecutionStatus.FAILED,
            completed_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            metadata=metadata,
        )

    def mark_cancelled(self) -> "PlanExecution":
        """Mark execution as cancelled. Returns new instance."""
        return replace(
            self,
            status=ExecutionStatus.CANCELLED,
            completed_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )

    def increment_reflection_cycle(self) -> "PlanExecution":
        """Increment reflection cycle count. Returns new instance."""
        return replace(
            self,
            current_reflection_cycle=self.current_reflection_cycle + 1,
            updated_at=datetime.now(timezone.utc),
        )

    @property
    def is_complete(self) -> bool:
        """Check if execution is complete (all steps done)."""
        if not self.steps:
            return True
        total = len(self.steps)
        done = len(self.completed_step_indices) + len(self.failed_step_indices)
        return done >= total

    @property
    def progress_percentage(self) -> float:
        """Get progress percentage."""
        if not self.steps:
            return 100.0
        total = len(self.steps)
        done = len(self.completed_step_indices) + len(self.failed_step_indices)
        return (done / total) * 100.0

    @property
    def completed_steps_count(self) -> int:
        """Get count of completed steps."""
        return len(self.completed_step_indices)

    @property
    def failed_steps_count(self) -> int:
        """Get count of failed steps."""
        return len(self.failed_step_indices)

    def add_metadata(self, key: str, value: Any) -> "PlanExecution":
        """Add metadata. Returns new instance."""
        new_metadata = dict(self.metadata)
        new_metadata[key] = value
        return replace(
            self,
            metadata=new_metadata,
            updated_at=datetime.now(timezone.utc),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "plan_id": self.plan_id,
            "steps": [step.to_dict() for step in self.steps],
            "current_step_index": self.current_step_index,
            "completed_step_indices": list(self.completed_step_indices),
            "failed_step_indices": list(self.failed_step_indices),
            "status": self.status.value,
            "execution_mode": self.execution_mode.value,
            "max_parallel_steps": self.max_parallel_steps,
            "reflection_enabled": self.reflection_enabled,
            "max_reflection_cycles": self.max_reflection_cycles,
            "current_reflection_cycle": self.current_reflection_cycle,
            "workflow_pattern_id": self.workflow_pattern_id,
            "metadata": dict(self.metadata),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanExecution":
        """Create PlanExecution from dictionary."""
        return cls(
            id=data["id"],
            conversation_id=data["conversation_id"],
            plan_id=data.get("plan_id"),
            steps=[ExecutionStep.from_dict(s) for s in data.get("steps", [])],
            current_step_index=data.get("current_step_index", 0),
            completed_step_indices=data.get("completed_step_indices", []),
            failed_step_indices=data.get("failed_step_indices", []),
            status=ExecutionStatus(data.get("status", "pending")),
            execution_mode=ExecutionMode(data.get("execution_mode", "sequential")),
            max_parallel_steps=data.get("max_parallel_steps", 3),
            reflection_enabled=data.get("reflection_enabled", True),
            max_reflection_cycles=data.get("max_reflection_cycles", 3),
            current_reflection_cycle=data.get("current_reflection_cycle", 0),
            workflow_pattern_id=data.get("workflow_pattern_id"),
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if data.get("updated_at")
            else None,
            started_at=datetime.fromisoformat(data["started_at"])
            if data.get("started_at")
            else None,
            completed_at=datetime.fromisoformat(data["completed_at"])
            if data.get("completed_at")
            else None,
        )
