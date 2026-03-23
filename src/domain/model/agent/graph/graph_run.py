"""GraphRun entity — aggregate root for a running graph instance."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.model.agent.graph.graph_run_status import GraphRunStatus
from src.domain.model.agent.graph.node_execution import NodeExecution
from src.domain.model.agent.graph.node_execution_status import NodeExecutionStatus
from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class GraphRun(Entity):
    """Aggregate root tracking the execution of an AgentGraph instance.

    A GraphRun is created when a graph is started and tracks all node
    executions, shared context, and overall run status until completion.

    Attributes:
        graph_id: ID of the AgentGraph definition being executed.
        conversation_id: Parent conversation that initiated this run.
        tenant_id: Tenant scope for multi-tenancy isolation.
        project_id: Project scope for multi-tenancy isolation.
        status: Current run status.
        node_executions: Map of node_id to NodeExecution tracking each node.
        shared_context: Shared key-value context accessible by all nodes.
        current_node_ids: Node IDs currently being executed.
        total_steps: Number of node transitions completed so far.
        max_total_steps: Maximum allowed transitions before forced termination.
        error_message: Error details if the run failed.
        started_at: When the run began.
        completed_at: When the run reached a terminal state.
        created_at: When this record was created.
    """

    graph_id: str
    conversation_id: str
    tenant_id: str
    project_id: str
    status: GraphRunStatus = GraphRunStatus.PENDING
    node_executions: dict[str, NodeExecution] = field(default_factory=dict)
    shared_context: dict[str, Any] = field(default_factory=dict)
    current_node_ids: list[str] = field(default_factory=list)
    total_steps: int = 0
    max_total_steps: int = 50
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.graph_id:
            raise ValueError("graph_id cannot be empty")
        if not self.conversation_id:
            raise ValueError("conversation_id cannot be empty")
        if not self.tenant_id:
            raise ValueError("tenant_id cannot be empty")
        if not self.project_id:
            raise ValueError("project_id cannot be empty")
        if self.max_total_steps < 1:
            raise ValueError("max_total_steps must be >= 1")

    def mark_running(self, entry_node_ids: list[str]) -> None:
        """Transition to RUNNING state with the initial entry nodes."""
        if self.status != GraphRunStatus.PENDING:
            raise ValueError(f"Cannot start graph run in {self.status} state")
        self.status = GraphRunStatus.RUNNING
        self.current_node_ids = list(entry_node_ids)
        self.started_at = datetime.now(UTC)

    def mark_completed(self) -> None:
        """Transition to COMPLETED state when all terminal nodes finish."""
        if self.status != GraphRunStatus.RUNNING:
            raise ValueError(f"Cannot complete graph run in {self.status} state")
        self.status = GraphRunStatus.COMPLETED
        self.current_node_ids = []
        self.completed_at = datetime.now(UTC)

    def mark_failed(self, error_message: str) -> None:
        """Transition to FAILED state with an error message."""
        if self.status != GraphRunStatus.RUNNING:
            raise ValueError(f"Cannot fail graph run in {self.status} state")
        self.status = GraphRunStatus.FAILED
        self.error_message = error_message
        self.current_node_ids = []
        self.completed_at = datetime.now(UTC)

    def mark_cancelled(self) -> None:
        """Transition to CANCELLED state."""
        if self.status.is_terminal:
            return  # Already in terminal state, no-op
        self.status = GraphRunStatus.CANCELLED
        self.current_node_ids = []
        self.completed_at = datetime.now(UTC)
        # Cancel all non-terminal node executions
        for node_exec in self.node_executions.values():
            node_exec.mark_cancelled()

    def add_node_execution(self, node_execution: NodeExecution) -> None:
        """Register a new node execution for tracking."""
        if node_execution.node_id in self.node_executions:
            raise ValueError(
                f"Node execution for node_id={node_execution.node_id} already exists in this run"
            )
        self.node_executions[node_execution.node_id] = node_execution

    def get_node_execution(self, node_id: str) -> NodeExecution | None:
        """Get the node execution for a specific node."""
        return self.node_executions.get(node_id)

    def increment_step(self) -> None:
        """Increment the step counter and check for step limit."""
        self.total_steps += 1
        if self.total_steps >= self.max_total_steps:
            self.mark_failed(f"Graph run exceeded maximum steps ({self.max_total_steps})")

    def update_shared_context(self, updates: dict[str, Any]) -> None:
        """Merge updates into the shared context."""
        self.shared_context.update(updates)

    @property
    def is_terminal(self) -> bool:
        """Check if this run has reached a terminal state."""
        return self.status.is_terminal

    @property
    def all_nodes_terminal(self) -> bool:
        """Check if all tracked node executions are in terminal states."""
        if not self.node_executions:
            return False
        return all(ne.is_terminal for ne in self.node_executions.values())

    @property
    def running_node_ids(self) -> list[str]:
        """Get IDs of nodes currently in RUNNING status."""
        return [
            nid
            for nid, ne in self.node_executions.items()
            if ne.status == NodeExecutionStatus.RUNNING
        ]

    @property
    def completed_node_ids(self) -> list[str]:
        """Get IDs of nodes that completed successfully."""
        return [
            nid
            for nid, ne in self.node_executions.items()
            if ne.status == NodeExecutionStatus.COMPLETED
        ]

    @property
    def failed_node_ids(self) -> list[str]:
        """Get IDs of nodes that failed."""
        return [
            nid
            for nid, ne in self.node_executions.items()
            if ne.status == NodeExecutionStatus.FAILED
        ]

    @property
    def duration_seconds(self) -> float | None:
        """Calculate run duration in seconds, or None if not completed."""
        if self.started_at is None or self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds()
