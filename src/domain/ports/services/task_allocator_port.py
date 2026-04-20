"""Port: capability-scored task allocation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from src.domain.model.workspace_plan import PlanNode


@dataclass(frozen=True)
class WorkspaceAgent:
    """Candidate agent the allocator can score.

    Kept minimal and orthogonal to ``AgentDefinition`` / ``WorkspaceAgentBinding``
    so the allocator stays a pure function.
    """

    agent_id: str
    display_name: str
    capabilities: frozenset[str] = field(default_factory=frozenset)
    tool_names: frozenset[str] = field(default_factory=frozenset)
    active_task_count: int = 0
    is_leader: bool = False
    is_available: bool = True
    affinity_tags: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class Allocation:
    """Pairing produced by the allocator."""

    node_id: str
    agent_id: str
    score: float
    reasons: tuple[str, ...] = field(default_factory=tuple)


class TaskAllocatorPort(Protocol):
    """Assigns ready :class:`PlanNode` s to :class:`WorkspaceAgent` s."""

    async def allocate(
        self,
        ready_nodes: list[PlanNode],
        pool: list[WorkspaceAgent],
    ) -> list[Allocation]:
        """Return at most one :class:`Allocation` per ready node.

        Nodes that cannot be allocated (no available agent, zero score) are
        simply omitted — the supervisor is expected to retry on the next tick.
        """
        ...
