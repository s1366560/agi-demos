"""Graph pattern coordinators package.

Provides scheduling strategies for each GraphPattern type.
Use ``get_coordinator_for_pattern()`` to obtain the correct
coordinator instance for a given pattern.
"""

from __future__ import annotations

from src.domain.model.agent.graph.graph_pattern import GraphPattern

from .base import PatternCoordinator
from .fan_out import FanOutCoordinator
from .pipeline import PipelineCoordinator
from .supervisor import SupervisorCoordinator
from .swarm import SwarmCoordinator

__all__ = [
    "FanOutCoordinator",
    "PatternCoordinator",
    "PipelineCoordinator",
    "SupervisorCoordinator",
    "SwarmCoordinator",
    "get_coordinator_for_pattern",
]

_PATTERN_COORDINATORS: dict[GraphPattern, type[PatternCoordinator]] = {
    GraphPattern.SUPERVISOR: SupervisorCoordinator,
    GraphPattern.PIPELINE: PipelineCoordinator,
    GraphPattern.FAN_OUT: FanOutCoordinator,
    GraphPattern.SWARM: SwarmCoordinator,
    # HIERARCHICAL uses the same scheduling as SUPERVISOR — the hierarchy
    # is expressed via nested graph runs, not a separate coordinator.
    GraphPattern.HIERARCHICAL: SupervisorCoordinator,
}


def get_coordinator_for_pattern(pattern: GraphPattern) -> PatternCoordinator:
    """Create and return a coordinator instance for the given pattern.

    Raises ValueError if the pattern is not recognized (should not
    happen with a well-formed GraphPattern enum).
    """
    coordinator_cls = _PATTERN_COORDINATORS.get(pattern)
    if coordinator_cls is None:
        raise ValueError(f"No coordinator registered for pattern: {pattern.value}")
    return coordinator_cls()
