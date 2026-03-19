"""Agent role definitions for multi-agent depth-based capability resolution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AgentRole(str, Enum):
    """Enum defining agent roles in the multi-agent system.

    Roles are assigned based on depth in the agent hierarchy:
    - MAIN: Root agent at depth 0
    - ORCHESTRATOR: Intermediate agents (0 < depth < max_depth)
    - LEAF: Terminal agents at depth >= max_depth
    """

    MAIN = "main"
    ORCHESTRATOR = "orchestrator"
    LEAF = "leaf"


@dataclass(frozen=True)
class RoleCapabilities:
    """Immutable value object defining capabilities for an agent role.

    Attributes:
        can_spawn: Whether this role can spawn sub-agents.
        can_control_children: Whether this role can control spawned sub-agents.
        can_control_siblings: Whether this role can control sibling agents.
        max_concurrent_children: Maximum number of concurrent child agents allowed.
        denied_tools: Set of tool names this role cannot execute.
    """

    can_spawn: bool
    can_control_children: bool
    can_control_siblings: bool
    max_concurrent_children: int
    denied_tools: frozenset[str]


ROLE_DEFAULTS: dict[AgentRole, RoleCapabilities] = {
    AgentRole.MAIN: RoleCapabilities(
        can_spawn=True,
        can_control_children=True,
        can_control_siblings=False,
        max_concurrent_children=8,
        denied_tools=frozenset(),
    ),
    AgentRole.ORCHESTRATOR: RoleCapabilities(
        can_spawn=True,
        can_control_children=True,
        can_control_siblings=False,
        max_concurrent_children=5,
        denied_tools=frozenset(),
    ),
    AgentRole.LEAF: RoleCapabilities(
        can_spawn=False,
        can_control_children=False,
        can_control_siblings=False,
        max_concurrent_children=0,
        denied_tools=frozenset({"spawn_agent", "delegate_to_subagent"}),
    ),
}


class AgentRoleResolver:
    """Pure function resolver for assigning roles based on agent depth."""

    @staticmethod
    def resolve(depth: int, max_depth: int) -> AgentRole:
        """Resolve agent role based on depth in the hierarchy.

        Args:
            depth: Current agent depth (0 = root).
            max_depth: Maximum allowed depth in the system.

        Returns:
            AgentRole assigned based on depth.

        Raises:
            ValueError: If depth < 0 or max_depth < 1.
        """
        if depth < 0:
            raise ValueError(f"Agent depth cannot be negative: {depth}")
        if max_depth < 1:
            raise ValueError(f"Max depth must be at least 1: {max_depth}")

        if depth == 0:
            return AgentRole.MAIN
        if depth >= max_depth:
            return AgentRole.LEAF
        return AgentRole.ORCHESTRATOR
