"""PlanNode: the atomic unit of a goal DAG.

``PlanNode`` replaces ``WorkspaceTask.metadata`` magic strings with typed fields:

* ``kind``              — goal / milestone / task / verify (see :class:`PlanNodeKind`)
* ``intent``            — user-facing status (TODO/IN_PROGRESS/BLOCKED/DONE)
* ``execution``         — orchestration transient (IDLE/DISPATCHED/RUNNING/...)
* ``depends_on``        — explicit DAG edges (replaces round-robin)
* ``recommended_capabilities`` — what tools/skills the worker should have
* ``inputs_schema`` / ``outputs_schema`` — JSON-Schema for structured I/O
* ``acceptance_criteria`` — list of machine-checkable completion criteria
* ``progress``          — numeric progress with confidence

The entity is mutable (it has a lifecycle) but individual state transitions go
through :mod:`state_machine` to enforce invariants.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from src.domain.model.workspace_plan.acceptance import AcceptanceCriterion
from src.domain.shared_kernel import Entity


class PlanNodeKind(str, Enum):
    """What role this node plays in the goal DAG.

    * ``GOAL``      — user-visible top-level objective (root of a plan)
    * ``MILESTONE`` — grouping node; has children but is typically not executed
    * ``TASK``      — leaf work assigned to a worker agent
    * ``VERIFY``    — dedicated verification step (runs acceptance criteria)
    """

    GOAL = "goal"
    MILESTONE = "milestone"
    TASK = "task"
    VERIFY = "verify"


class TaskIntent(str, Enum):
    """User-facing lifecycle status. Stable, small, 4 values.

    This is what a UI renders; transitions are driven by:

    * worker reports    → ``TODO -> IN_PROGRESS``
    * verifier verdict  → ``IN_PROGRESS -> DONE | BLOCKED``
    * human escalation  → ``* -> BLOCKED``
    * replan            → ``BLOCKED -> TODO``
    """

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"


class TaskExecution(str, Enum):
    """Orchestration transient status. Hidden from most UI.

    Canonical happy path: ``IDLE → DISPATCHED → RUNNING → REPORTED → VERIFYING → IDLE (or terminal)``.
    """

    IDLE = "idle"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    REPORTED = "reported"
    VERIFYING = "verifying"


@dataclass(frozen=True)
class Effort:
    """Coarse effort estimate. Kept as a value object so schedulers can plan."""

    minutes: int = 0
    confidence: float = 0.5  # 0..1 — planner's self-assessed confidence

    def __post_init__(self) -> None:
        if self.minutes < 0:
            raise ValueError("Effort.minutes must be >= 0")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Effort.confidence must be in [0,1]")


@dataclass(frozen=True)
class Progress:
    """Numeric progress snapshot for a node."""

    percent: float = 0.0  # 0..100
    confidence: float = 1.0  # 0..1
    note: str = ""

    def __post_init__(self) -> None:
        if not 0.0 <= self.percent <= 100.0:
            raise ValueError("Progress.percent must be in [0,100]")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("Progress.confidence must be in [0,1]")


@dataclass(frozen=True)
class Capability:
    """A capability name + optional weight the planner attaches to a node.

    Used by :class:`TaskAllocatorPort` to score agent/task fit. Common names:
    ``"web_search"``, ``"codegen"``, ``"file_edit"``, ``"shell"``, ``"mcp.<tool>"``.
    """

    name: str
    weight: float = 1.0  # relative importance if multiple are required

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Capability.name cannot be empty")
        if self.weight <= 0.0:
            raise ValueError("Capability.weight must be > 0")


@dataclass(frozen=True)
class PlanNodeId:
    """Typed id wrapper so we can't accidentally pass a WorkspaceTask id here."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise ValueError("PlanNodeId.value cannot be empty")

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


@dataclass(kw_only=True)
class PlanNode(Entity):
    """A node in the goal DAG."""

    plan_id: str
    parent_id: PlanNodeId | None = None
    kind: PlanNodeKind = PlanNodeKind.TASK
    title: str
    description: str = ""

    # DAG edges. ``depends_on`` is the set of sibling/cousin nodes that must
    # reach TaskIntent.DONE before this node becomes "ready".
    depends_on: frozenset[PlanNodeId] = field(default_factory=frozenset)

    # Structured I/O contracts. JSON Schemas — validated by Verifier.
    inputs_schema: dict[str, Any] = field(default_factory=dict)
    outputs_schema: dict[str, Any] = field(default_factory=dict)

    # Machine-checkable completion criteria.
    acceptance_criteria: tuple[AcceptanceCriterion, ...] = field(default_factory=tuple)

    # Allocation hints.
    recommended_capabilities: tuple[Capability, ...] = field(default_factory=tuple)
    preferred_agent_id: str | None = None
    estimated_effort: Effort = field(default_factory=Effort)
    priority: int = 0  # higher is more urgent

    # Status (two orthogonal axes).
    intent: TaskIntent = TaskIntent.TODO
    execution: TaskExecution = TaskExecution.IDLE

    # Progress and binding (set by supervisor/verifier).
    progress: Progress = field(default_factory=Progress)
    assignee_agent_id: str | None = None
    current_attempt_id: str | None = None

    # Linkage back to legacy WorkspaceTask (adapter-bridge).
    workspace_task_id: str | None = None

    # Freeform metadata for migration compatibility — do not add new consumers.
    metadata: dict[str, Any] = field(default_factory=dict)

    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
    completed_at: datetime | None = None

    # --- Invariants -----------------------------------------------------

    def __post_init__(self) -> None:
        if not self.plan_id:
            raise ValueError("PlanNode.plan_id cannot be empty")
        if not self.title.strip():
            raise ValueError("PlanNode.title cannot be empty")
        if self.priority < 0:
            raise ValueError("PlanNode.priority must be >= 0")
        if self.kind is PlanNodeKind.GOAL and self.parent_id is not None:
            raise ValueError("goal node must have parent_id=None")
        if self.kind is not PlanNodeKind.GOAL and self.parent_id is None:
            # A root node is always the goal. Non-goals must point upward.
            # Milestones/tasks without a parent indicate a bug.
            raise ValueError(f"{self.kind.value} node must have a parent_id")
        if self.node_id in self.depends_on:
            raise ValueError("PlanNode.depends_on cannot contain self")

    # --- Convenience ----------------------------------------------------

    @property
    def node_id(self) -> PlanNodeId:
        return PlanNodeId(self.id)

    def is_terminal(self) -> bool:
        """True if the node has reached a terminal intent state."""
        return self.intent is TaskIntent.DONE

    def is_ready(self, completed_ids: frozenset[PlanNodeId]) -> bool:
        """True if all dependencies are done and intent is TODO.

        ``completed_ids`` is the caller-supplied set of sibling ids that have
        reached ``TaskIntent.DONE``. Ready nodes are the scheduling frontier.
        """
        if self.intent is not TaskIntent.TODO:
            return False
        return self.depends_on.issubset(completed_ids)

    def with_intent(self, intent: TaskIntent) -> PlanNode:
        """Return a shallow copy with ``intent`` updated. State-machine aware
        callers use :func:`transition_intent` first to validate."""
        from dataclasses import replace

        return replace(self, intent=intent, updated_at=datetime.now(UTC))

    def with_execution(self, execution: TaskExecution) -> PlanNode:
        from dataclasses import replace

        return replace(self, execution=execution, updated_at=datetime.now(UTC))

    def with_progress(self, progress: Progress) -> PlanNode:
        from dataclasses import replace

        return replace(self, progress=progress, updated_at=datetime.now(UTC))
