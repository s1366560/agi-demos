"""Swarm pattern coordinator.

Agent-driven handoffs: only the entry node is auto-scheduled.
Subsequent nodes are triggered exclusively via HandoffTool calls
from within a running agent. The coordinator validates that a
handoff target exists in the graph but does NOT auto-schedule
successors.
"""

from __future__ import annotations

from src.domain.model.agent.graph import AgentGraph, GraphRun
from src.domain.model.agent.graph.node_execution_status import NodeExecutionStatus


class SwarmCoordinator:
    """Agent-driven execution via explicit handoffs.

    The orchestrator only auto-launches entry nodes. All subsequent
    scheduling is driven by HandoffTool invocations from within
    running agents. ``get_next_node_ids`` returns successors ONLY
    on the very first call (entry nodes).
    """

    def get_next_node_ids(self, graph: AgentGraph, run: GraphRun) -> list[str]:
        if run.is_terminal:
            return []

        if not run.node_executions:
            return [n.node_id for n in graph.entry_nodes]

        return []

    def should_complete_run(self, graph: AgentGraph, run: GraphRun) -> bool:
        terminal_complete = all(
            (ne := run.get_node_execution(t.node_id)) is not None
            and ne.status == NodeExecutionStatus.COMPLETED
            for t in graph.terminal_nodes
        )
        if terminal_complete:
            return True

        # Deadlock prevention: all settled, none running
        if not run.running_node_ids and run.node_executions:
            all_settled = all(ne.is_terminal for ne in run.node_executions.values())
            return all_settled

        return False

    def validate_handoff_target(
        self, graph: AgentGraph, run: GraphRun, target_node_id: str
    ) -> str | None:
        """Validate that a handoff target is a valid, unexecuted node in the graph.

        Returns None on success, or an error message string on failure.
        """
        if target_node_id not in graph.node_ids:
            return f"Handoff target '{target_node_id}' does not exist in graph"

        existing = run.get_node_execution(target_node_id)
        if existing is not None and existing.status != NodeExecutionStatus.FAILED:
            return (
                f"Handoff target '{target_node_id}' already has execution "
                f"in status {existing.status.value}"
            )

        return None
