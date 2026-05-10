"""Agent-first structured decision broker boundary.

The broker is the only boundary allowed to turn semantic facts into a
runtime verdict. Callers may still enforce schema, enum, permission, budget,
and identity checks deterministically, but routing/classification/retry
judgments must arrive through this structured result shape.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class AgentDecisionKind(str, Enum):
    """Supported semantic decision surfaces."""

    WORKSPACE_VERIFICATION_RETRY = "workspace_verification_retry"
    WORKSPACE_BLOCKED_REPORT_CLASSIFICATION = "workspace_blocked_report_classification"
    EXECUTION_ROUTE = "execution_route"
    SKILL_ACTIVATION = "skill_activation"
    SUBAGENT_SELECTION = "subagent_selection"
    TOOL_RANKING = "tool_ranking"
    TASK_CATEGORY = "task_category"


@dataclass(frozen=True)
class AgentDecisionCandidate:
    """A structured option the broker can choose from."""

    id: str
    label: str = ""
    facts: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentDecisionRequest:
    """Structured facts submitted to an agent-backed decision broker."""

    decision_kind: AgentDecisionKind
    context_id: str
    facts: Mapping[str, Any] = field(default_factory=dict)
    candidates: Sequence[AgentDecisionCandidate] = field(default_factory=tuple)
    allowed_verdicts: Sequence[str] = field(default_factory=tuple)
    constraints: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentDecisionResult:
    """Structured verdict returned by a broker submit tool."""

    verdict: str
    rationale: str
    confidence: float
    selected_ids: Sequence[str] = field(default_factory=tuple)
    next_action_kind: str = ""
    repair_brief: Mapping[str, Any] = field(default_factory=dict)
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate structural fields without interpreting their meaning."""
        if not self.verdict:
            raise ValueError("verdict cannot be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


class AgentDecisionBrokerPort(Protocol):
    """Protocol for agent-backed structured decision brokers."""

    async def decide(self, request: AgentDecisionRequest) -> AgentDecisionResult:
        """Return a structured agent verdict for *request*."""
        ...
