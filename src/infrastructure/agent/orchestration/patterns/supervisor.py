"""Supervisor pattern coordinator.

Schedules one node at a time, following the DAG edges sequentially.
The supervisor (entry node) runs first, then delegates to successors
one by one based on edge ordering. Only one node runs at any moment.
"""

from __future__ import annotations

from src.domain.model.agent.graph import AgentGraph, GraphRun
from src.domain.model.agent.graph.node_execution_status import NodeExecutionStatus


class SupervisorCoordinator:
    def get_next_node_ids(self, graph: AgentGraph, run: GraphRun) -> list[str]:
        if run.is_terminal:
            return []

        if run.running_node_ids:
            return []

        if not run.node_executions:
            return [n.node_id for n in graph.entry_nodes]

        for node in graph.nodes:
            ne = run.get_node_execution(node.node_id)
            if ne is not None:
                continue

            predecessors = graph.get_predecessors(node.node_id)
            if not predecessors:
                continue

            all_predecessors_done = all(
                (pred_ne := run.get_node_execution(e.source_node_id)) is not None
                and pred_ne.status == NodeExecutionStatus.COMPLETED
                for e in predecessors
            )
            if all_predecessors_done:
                return [node.node_id]

        return []

    def should_complete_run(self, graph: AgentGraph, run: GraphRun) -> bool:
        return all(
            (ne := run.get_node_execution(t.node_id)) is not None
            and ne.status == NodeExecutionStatus.COMPLETED
            for t in graph.terminal_nodes
        )
