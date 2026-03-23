"""NodeExecution entity — tracks individual node execution within a graph run."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.model.agent.graph.node_execution_status import NodeExecutionStatus
from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class NodeExecution(Entity):
    """Tracks the execution lifecycle of a single node within a graph run.

    Each NodeExecution maps to one AgentNode in the graph definition and
    records the status, timing, and context of that node's agent session.

    Attributes:
        graph_run_id: ID of the parent GraphRun.
        node_id: ID of the AgentNode being executed.
        agent_session_id: Session ID of the spawned agent (set when execution starts).
        status: Current execution status.
        input_context: Context passed to this node at execution start.
        output_context: Context produced by this node upon completion.
        error_message: Error details if the node failed.
        started_at: When execution began.
        completed_at: When execution reached a terminal state.
    """

    graph_run_id: str
    node_id: str
    agent_session_id: str | None = None
    status: NodeExecutionStatus = NodeExecutionStatus.PENDING
    input_context: dict[str, Any] = field(default_factory=dict)
    output_context: dict[str, Any] = field(default_factory=dict)
    error_message: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.graph_run_id:
            raise ValueError("graph_run_id cannot be empty")
        if not self.node_id:
            raise ValueError("node_id cannot be empty")

    def mark_running(self, agent_session_id: str) -> None:
        """Transition to RUNNING state when the agent session is spawned."""
        if self.status != NodeExecutionStatus.PENDING:
            raise ValueError(f"Cannot start node execution in {self.status} state")
        self.status = NodeExecutionStatus.RUNNING
        self.agent_session_id = agent_session_id
        self.started_at = datetime.now(UTC)

    def mark_completed(self, output_context: dict[str, Any] | None = None) -> None:
        """Transition to COMPLETED state with optional output context."""
        if self.status != NodeExecutionStatus.RUNNING:
            raise ValueError(f"Cannot complete node execution in {self.status} state")
        self.status = NodeExecutionStatus.COMPLETED
        if output_context is not None:
            self.output_context = output_context
        self.completed_at = datetime.now(UTC)

    def mark_failed(self, error_message: str) -> None:
        """Transition to FAILED state with an error message."""
        if self.status != NodeExecutionStatus.RUNNING:
            raise ValueError(f"Cannot fail node execution in {self.status} state")
        self.status = NodeExecutionStatus.FAILED
        self.error_message = error_message
        self.completed_at = datetime.now(UTC)

    def mark_skipped(self) -> None:
        """Transition to SKIPPED state (conditional edge not satisfied)."""
        if self.status != NodeExecutionStatus.PENDING:
            raise ValueError(f"Cannot skip node execution in {self.status} state")
        self.status = NodeExecutionStatus.SKIPPED
        self.completed_at = datetime.now(UTC)

    def mark_cancelled(self) -> None:
        """Transition to CANCELLED state (graph cancelled or timeout)."""
        if self.status.is_terminal:
            return  # Already in terminal state, no-op
        self.status = NodeExecutionStatus.CANCELLED
        self.completed_at = datetime.now(UTC)

    @property
    def is_terminal(self) -> bool:
        """Check if this node execution has reached a terminal state."""
        return self.status.is_terminal

    @property
    def duration_seconds(self) -> float | None:
        """Calculate execution duration in seconds, or None if not completed."""
        if self.started_at is None or self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds()
