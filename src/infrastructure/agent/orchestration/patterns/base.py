"""Base protocol for graph pattern coordinators."""

from __future__ import annotations

from typing import Protocol

from src.domain.model.agent.graph import AgentGraph, GraphRun


class PatternCoordinator(Protocol):
    """Protocol that all graph pattern coordinators must satisfy.

    A PatternCoordinator decides which nodes to execute next based on
    the current graph run state, the graph definition, and the pattern
    semantics (supervisor, pipeline, fan-out, swarm, hierarchical).
    """

    def get_next_node_ids(self, graph: AgentGraph, run: GraphRun) -> list[str]:
        """Return node IDs that should be scheduled for execution next.

        Returns an empty list when no more nodes should be scheduled
        (either the run is complete, waiting on running nodes, or failed).
        """
        ...

    def should_complete_run(self, graph: AgentGraph, run: GraphRun) -> bool:
        """Check if the graph run should transition to COMPLETED.

        Called after a node finishes. Returns True when the pattern
        determines that all required work is done.
        """
        ...
