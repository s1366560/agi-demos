"""
PlanSnapshot domain model for Plan Mode rollback functionality.

Defines snapshots that capture plan state at a point in time.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict

from src.domain.shared_kernel import Entity


@dataclass(frozen=True)
class StepState:
    """
    Immutable snapshot of a single step's state.

    Used for rollback functionality in Plan Mode.
    """

    step_id: str
    status: str
    result: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    tool_input: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "step_id": self.step_id,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "tool_input": self.tool_input,
        }

    @classmethod
    def from_execution_step(cls, step: Any) -> "StepState":
        """Create StepState from an ExecutionStep."""
        from src.domain.model.agent.execution_plan import ExecutionStepStatus

        # Validate input type
        if not hasattr(step, "step_id"):
            raise TypeError(f"Expected ExecutionStep, got {type(step)}")

        return cls(
            step_id=step.step_id,
            status=step.status.value if isinstance(step.status, ExecutionStepStatus) else str(step.status),
            result=step.result,
            error=step.error,
            started_at=step.started_at,
            completed_at=step.completed_at,
            tool_input=dict(step.tool_input) if hasattr(step, "tool_input") else {},
        )


@dataclass(kw_only=True)
class PlanSnapshot(Entity):
    """
    A snapshot of an ExecutionPlan at a point in time.

    Used for rollback functionality in Plan Mode. Supports both
    automatic snapshots (after each step) and named snapshots
    (user-created checkpoints).

    Attributes:
        plan_id: ID of the plan this snapshot belongs to
        name: Human-readable name for this snapshot
        step_states: Dictionary mapping step_id -> StepState
        description: Optional description of what this snapshot represents
        auto_created: Whether this was automatically created
        snapshot_type: Type of snapshot ('last_step', 'named')
    """

    plan_id: str
    name: str
    step_states: Dict[str, StepState]
    description: str | None = None
    auto_created: bool = True
    snapshot_type: str = "last_step"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def get_step_state(self, step_id: str) -> StepState | None:
        """Get the state of a specific step from this snapshot."""
        return self.step_states.get(step_id)

    def has_step_state(self, step_id: str) -> bool:
        """Check if this snapshot contains state for a step."""
        return step_id in self.step_states

    @classmethod
    def create_named(
        cls,
        plan_id: str,
        name: str,
        step_states: Dict[str, StepState],
        description: str | None = None,
    ) -> "PlanSnapshot":
        """Factory method to create a user-named snapshot."""
        return cls(
            plan_id=plan_id,
            name=name,
            step_states=step_states,
            description=description,
            auto_created=False,
            snapshot_type="named",
        )

    @classmethod
    def create_auto(
        cls,
        plan_id: str,
        snapshot_type: str,
        step_states: Dict[str, StepState],
    ) -> "PlanSnapshot":
        """Factory method to create an automatic snapshot."""
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        return cls(
            plan_id=plan_id,
            name=f"Auto snapshot {timestamp}",
            step_states=step_states,
            auto_created=True,
            snapshot_type=snapshot_type,
        )

    @classmethod
    def from_execution_plan(
        cls,
        plan: Any,
        name: str,
        description: str | None = None,
        auto_created: bool = True,
    ) -> "PlanSnapshot":
        """Create a snapshot from an ExecutionPlan."""
        from src.domain.model.agent.plan_snapshot import StepState

        step_states: dict[str, StepState] = {}
        for step in plan.steps:
            step_states[step.step_id] = StepState.from_execution_step(step)

        return cls(
            plan_id=plan.id,
            name=name,
            step_states=step_states,
            description=description,
            auto_created=auto_created,
            snapshot_type="named" if not auto_created else "last_step",
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "plan_id": self.plan_id,
            "name": self.name,
            "description": self.description,
            "step_states": {
                step_id: state.to_dict() for step_id, state in self.step_states.items()
            },
            "auto_created": self.auto_created,
            "snapshot_type": self.snapshot_type,
            "created_at": self.created_at.isoformat(),
        }
