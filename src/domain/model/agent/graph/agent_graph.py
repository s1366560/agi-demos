"""AgentGraph entity — DAG definition for multi-agent orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.model.agent.graph.agent_edge import AgentEdge
from src.domain.model.agent.graph.agent_node import AgentNode
from src.domain.model.agent.graph.graph_pattern import GraphPattern
from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class AgentGraph(Entity):
    tenant_id: str
    project_id: str
    name: str
    description: str = ""
    pattern: GraphPattern = GraphPattern.SUPERVISOR
    nodes: list[AgentNode] = field(default_factory=list)
    edges: list[AgentEdge] = field(default_factory=list)
    shared_context_keys: list[str] = field(default_factory=list)
    max_total_steps: int = 50
    metadata: dict[str, Any] = field(default_factory=dict)
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.tenant_id:
            raise ValueError("tenant_id cannot be empty")
        if not self.project_id:
            raise ValueError("project_id cannot be empty")
        if not self.name:
            raise ValueError("name cannot be empty")
        if self.max_total_steps < 1:
            raise ValueError("max_total_steps must be >= 1")

    @property
    def entry_nodes(self) -> list[AgentNode]:
        return [n for n in self.nodes if n.is_entry]

    @property
    def terminal_nodes(self) -> list[AgentNode]:
        return [n for n in self.nodes if n.is_terminal]

    @property
    def node_ids(self) -> set[str]:
        return {n.node_id for n in self.nodes}

    def get_node(self, node_id: str) -> AgentNode | None:
        for node in self.nodes:
            if node.node_id == node_id:
                return node
        return None

    def get_successors(self, node_id: str) -> list[AgentEdge]:
        return [e for e in self.edges if e.source_node_id == node_id]

    def get_predecessors(self, node_id: str) -> list[AgentEdge]:
        return [e for e in self.edges if e.target_node_id == node_id]

    def _detect_cycles(self, node_ids: set[str]) -> bool:
        """Return True if the graph contains a cycle (Kahn's algorithm)."""
        in_degree: dict[str, int] = dict.fromkeys(node_ids, 0)
        for edge in self.edges:
            in_degree[edge.target_node_id] = in_degree.get(edge.target_node_id, 0) + 1

        queue = [nid for nid, deg in in_degree.items() if deg == 0]
        visited_count = 0
        while queue:
            current = queue.pop(0)
            visited_count += 1
            for edge in self.get_successors(current):
                in_degree[edge.target_node_id] -= 1
                if in_degree[edge.target_node_id] == 0:
                    queue.append(edge.target_node_id)

        return visited_count != len(node_ids)

    def validate_graph(self) -> list[str]:
        """Validate graph structure, returning a list of error messages (empty if valid)."""
        errors: list[str] = []
        node_ids = self.node_ids

        if not self.nodes:
            errors.append("graph must have at least one node")
            return errors

        if not self.entry_nodes:
            errors.append("graph must have at least one entry node")

        if not self.terminal_nodes:
            errors.append("graph must have at least one terminal node")

        for edge in self.edges:
            if edge.source_node_id not in node_ids:
                errors.append(f"edge references unknown source node: {edge.source_node_id}")
            if edge.target_node_id not in node_ids:
                errors.append(f"edge references unknown target node: {edge.target_node_id}")

        if not errors and self._detect_cycles(node_ids):
            errors.append("graph contains a cycle")

        return errors
