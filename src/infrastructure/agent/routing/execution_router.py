"""Execution Router types for ReActAgent.

Retained types from the original confidence-scoring router.
The ExecutionRouter class and its Protocol dependencies have been
removed (Wave 1a). Routing now happens via prompt-driven lane
detection in ReActAgent._decide_execution_path().
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any


class ExecutionPath(Enum):
    """Possible execution paths for a request."""

    DIRECT_SKILL = "direct_skill"  # Execute skill directly without LLM
    # SUBAGENT removed in Wave 5 -- subagents are now tools in the ReAct loop
    PLAN_MODE = "plan_mode"  # Use planning mode
    REACT_LOOP = "react_loop"  # Standard ReAct reasoning loop


@dataclass
class RoutingDecision:
    """Result of routing analysis."""

    path: ExecutionPath
    confidence: float  # 0.0 to 1.0
    reason: str
    target: str | None = None  # Skill/subagent name if applicable
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}
