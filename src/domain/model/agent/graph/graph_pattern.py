"""Graph orchestration pattern enumeration."""

from enum import Enum
from typing import override


class GraphPattern(str, Enum):
    """Orchestration pattern for multi-agent graph execution.

    Attributes:
        SUPERVISOR: Central coordinator dispatches to worker agents, aggregates results.
        PIPELINE: Sequential chain where each agent's output feeds the next.
        FAN_OUT: Parallel dispatch to multiple agents, then aggregate.
        SWARM: Peer-to-peer handoff where agents decide the next agent dynamically.
        HIERARCHICAL: Multi-level supervisor tree with sub-supervisors.
    """

    SUPERVISOR = "supervisor"
    PIPELINE = "pipeline"
    FAN_OUT = "fan_out"
    SWARM = "swarm"
    HIERARCHICAL = "hierarchical"

    @override
    def __str__(self) -> str:
        return self.value
