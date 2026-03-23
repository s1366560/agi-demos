"""Fan-out pattern coordinator.

Launches all eligible successors in parallel when a predecessor completes.
A node becomes eligible only when ALL its predecessors have completed.
Multiple nodes can run simultaneously, enabling parallelism.
"""

from __future__ import annotations

from src.domain.model.agent.graph import AgentGraph, GraphRun
from src.domain.model.agent.graph.node_execution_status import NodeExecutionStatus


class FanOutCoordinator:
    """Parallel execution with dependency-aware scheduling.

    Unlike Supervisor/Pipeline (one at a time), FanOut launches
    ALL ready nodes simultaneously. A node is ready when every
    predecessor has completed.
    """

    def get_next_node_ids(self, graph: AgentGraph, run: GraphRun) -> list[str]:
        if run.is_terminal:
            return []

        if not run.node_executions:
            return [n.node_id for n in graph.entry_nodes]

        ready: list[str] = []
        for node in graph.nodes:
            ne = run.get_node_execution(node.node_id)
            if ne is not None:
                continue

            predecessors = graph.get_predecessors(node.node_id)
            if not predecessors:
                ready.append(node.node_id)
                continue

            all_predecessors_done = all(
                (pred_ne := run.get_node_execution(e.source_node_id)) is not None
                and pred_ne.status == NodeExecutionStatus.COMPLETED
                for e in predecessors
            )
            if all_predecessors_done:
                ready.append(node.node_id)

        return ready

    def should_complete_run(self, graph: AgentGraph, run: GraphRun) -> bool:
        return all(
            (ne := run.get_node_execution(t.node_id)) is not None
            and ne.status == NodeExecutionStatus.COMPLETED
            for t in graph.terminal_nodes
        )
