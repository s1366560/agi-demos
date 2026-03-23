"""Pipeline pattern coordinator.

Executes nodes in strict topological order, one at a time.
Each node must complete before the next starts. Unlike Supervisor,
Pipeline uses topological sort to determine ordering rather than
relying solely on edge traversal from the last completed node.
"""

from __future__ import annotations

from src.domain.model.agent.graph import AgentGraph, GraphRun
from src.domain.model.agent.graph.node_execution_status import NodeExecutionStatus


class PipelineCoordinator:
    """Linear chain execution following topological order.

    Nodes are executed one at a time in topologically sorted order.
    A node is eligible only when all its predecessors have completed.
    """

    def get_next_node_ids(self, graph: AgentGraph, run: GraphRun) -> list[str]:
        if run.is_terminal:
            return []

        if run.running_node_ids:
            return []

        if not run.node_executions:
            return [n.node_id for n in graph.entry_nodes][:1]

        for node_id in self._topological_order(graph):
            ne = run.get_node_execution(node_id)
            if ne is not None:
                continue

            predecessors = graph.get_predecessors(node_id)
            all_done = all(
                (pred_ne := run.get_node_execution(e.source_node_id)) is not None
                and pred_ne.status == NodeExecutionStatus.COMPLETED
                for e in predecessors
            )
            if all_done:
                return [node_id]

        return []

    def should_complete_run(self, graph: AgentGraph, run: GraphRun) -> bool:
        return all(
            (ne := run.get_node_execution(t.node_id)) is not None
            and ne.status == NodeExecutionStatus.COMPLETED
            for t in graph.terminal_nodes
        )

    @staticmethod
    def _topological_order(graph: AgentGraph) -> list[str]:
        """Kahn's algorithm for a deterministic topological ordering."""
        in_degree: dict[str, int] = {n.node_id: 0 for n in graph.nodes}
        for edge in graph.edges:
            in_degree[edge.target_node_id] = in_degree.get(edge.target_node_id, 0) + 1

        queue = sorted(nid for nid, deg in in_degree.items() if deg == 0)
        order: list[str] = []
        while queue:
            current = queue.pop(0)
            order.append(current)
            successors = sorted(e.target_node_id for e in graph.get_successors(current))
            for target in successors:
                in_degree[target] -= 1
                if in_degree[target] == 0:
                    queue.append(target)

        return order
