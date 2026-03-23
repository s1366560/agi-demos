"""Agent node value object for graph definitions."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentNode:
    """A node in an agent graph representing a single agent execution point.

    Each node maps to an agent definition (by agent_definition_id) and carries
    configuration for how that agent should be invoked within the graph.
    """

    node_id: str
    agent_definition_id: str
    label: str
    instruction: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    is_entry: bool = False
    is_terminal: bool = False

    def __post_init__(self) -> None:
        if not self.node_id:
            raise ValueError("node_id cannot be empty")
        if not self.agent_definition_id:
            raise ValueError("agent_definition_id cannot be empty")
        if not self.label:
            raise ValueError("label cannot be empty")
