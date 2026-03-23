"""Agent edge value object for graph definitions."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentEdge:
    """A directed edge connecting two nodes in an agent graph.

    Edges define execution flow between agents. The optional condition field
    allows conditional routing (e.g., only follow this edge if the source
    agent's output matches a pattern).
    """

    source_node_id: str
    target_node_id: str
    condition: str = ""

    def __post_init__(self) -> None:
        if not self.source_node_id:
            raise ValueError("source_node_id cannot be empty")
        if not self.target_node_id:
            raise ValueError("target_node_id cannot be empty")
        if self.source_node_id == self.target_node_id:
            raise ValueError("self-loops are not allowed")
