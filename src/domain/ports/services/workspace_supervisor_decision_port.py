"""Structured Agent-First supervisor decision port."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class WorkspaceSupervisorDecisionAction(str, Enum):
    """Next durable-plan action chosen by the supervisor decision agent."""

    ACCEPT_NODE = "accept_node"
    REQUEST_PIPELINE = "request_pipeline"
    WAIT_PIPELINE = "wait_pipeline"
    RETRY_SAME_NODE = "retry_same_node"
    CREATE_REPAIR_NODE = "create_repair_node"
    MARK_BLOCKED_HUMAN = "mark_blocked_human"
    DISPOSE_NODE = "dispose_node"
    REPLAN_NODE = "replan_node"
    NOOP = "noop"


@dataclass(frozen=True)
class WorkspaceSupervisorDecisionRequest:
    """Bounded facts passed to the supervisor decision agent."""

    workspace_id: str
    plan_id: str
    node_id: str
    attempt_id: str | None
    linked_workspace_task_id: str | None = None
    node_snapshot: dict[str, Any] = field(default_factory=dict)
    verification_report: dict[str, Any] = field(default_factory=dict)
    structural_signals: dict[str, Any] = field(default_factory=dict)
    allowed_actions: tuple[WorkspaceSupervisorDecisionAction, ...] = field(
        default_factory=tuple
    )
    recent_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkspaceSupervisorDecisionResult:
    """Structured result returned by the supervisor decision agent."""

    action: WorkspaceSupervisorDecisionAction
    rationale: str
    confidence: float = 0.0
    feedback_items: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    retry_not_before_seconds: int | None = None
    repair_brief: dict[str, Any] = field(default_factory=dict)
    event_payload: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("WorkspaceSupervisorDecisionResult.confidence must be in [0,1]")


class WorkspaceSupervisorDecisionPort(Protocol):
    """Agent-First semantic action boundary for durable supervisor ticks."""

    async def decide(
        self,
        request: WorkspaceSupervisorDecisionRequest,
    ) -> WorkspaceSupervisorDecisionResult: ...


__all__ = [
    "WorkspaceSupervisorDecisionAction",
    "WorkspaceSupervisorDecisionPort",
    "WorkspaceSupervisorDecisionRequest",
    "WorkspaceSupervisorDecisionResult",
]
