"""Structured Agent-First verification judgment port."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class WorkspaceVerificationJudgeVerdict(str, Enum):
    """Final semantic verdict for a reported workspace plan node."""

    ACCEPTED = "accepted"
    NEEDS_REWORK = "needs_rework"
    BLOCKED_HUMAN_REQUIRED = "blocked_human_required"
    RETRY_INFRASTRUCTURE = "retry_infrastructure"


class WorkspaceVerificationNextActionKind(str, Enum):
    """Structured next action requested by the verification judge."""

    NONE = "none"
    RETRY_SAME_NODE = "retry_same_node"
    CREATE_REPAIR_NODE = "create_repair_node"
    HUMAN_REQUIRED = "human_required"


class WorkspaceVerificationFeedbackTargetLayer(str, Enum):
    """System layer that should consume verifier feedback."""

    WORKER = "worker"
    PLANNER = "planner"
    REVIEWER = "reviewer"
    RUNTIME = "runtime"
    VERIFIER_POLICY = "verifier_policy"
    HUMAN = "human"


class WorkspaceVerificationFeedbackKind(str, Enum):
    """Structured verifier feedback category."""

    WORKER_OUTPUT_INCOMPLETE = "worker_output_incomplete"
    STALE_OR_INVALID_TASK_TARGET = "stale_or_invalid_task_target"
    MISSING_EVIDENCE = "missing_evidence"
    TEST_POLICY_CONFLICT = "test_policy_conflict"
    RUNTIME_INFRA_FAILURE = "runtime_infra_failure"
    PRODUCT_CODE_FAILURE = "product_code_failure"
    PLAN_SCOPE_MISMATCH = "plan_scope_mismatch"


class WorkspaceVerificationFeedbackSeverity(str, Enum):
    """Feedback severity for routing and UI aggregation."""

    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class WorkspaceVerificationRecommendedAction(str, Enum):
    """Recommended consumer action for a verifier feedback item."""

    RETRY_WORKER = "retry_worker"
    REVISE_PLAN_NODE = "revise_plan_node"
    OBSOLETE_NODE = "obsolete_node"
    CREATE_REPAIR_NODE = "create_repair_node"
    RETRY_INFRA = "retry_infra"
    ESCALATE_HUMAN = "escalate_human"
    ACCEPT_WITH_DISPOSITION = "accept_with_disposition"


@dataclass(frozen=True)
class WorkspaceVerificationFeedbackItem:
    """Layer-targeted feedback emitted by the verification judge."""

    target_layer: WorkspaceVerificationFeedbackTargetLayer
    feedback_kind: WorkspaceVerificationFeedbackKind
    severity: WorkspaceVerificationFeedbackSeverity
    recommended_action: WorkspaceVerificationRecommendedAction
    summary: str = ""
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    failure_signature: str = ""

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "target_layer": self.target_layer.value,
            "feedback_kind": self.feedback_kind.value,
            "severity": self.severity.value,
            "recommended_action": self.recommended_action.value,
        }
        if self.summary:
            payload["summary"] = self.summary
        if self.evidence_refs:
            payload["evidence_refs"] = list(self.evidence_refs)
        if self.failure_signature:
            payload["failure_signature"] = self.failure_signature
        return payload


@dataclass(frozen=True)
class WorkspaceVerificationJudgeRequest:
    """Bounded context passed to the verification judge agent."""

    workspace_id: str
    node_id: str
    attempt_id: str | None
    node_title: str
    node_description: str
    linked_workspace_task_id: str | None = None
    acceptance_criteria: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    worker_summary: str = ""
    candidate_artifacts: tuple[str, ...] = field(default_factory=tuple)
    candidate_verifications: tuple[str, ...] = field(default_factory=tuple)
    task_evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    latest_verification_results: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    guard_failures: tuple[str, ...] = field(default_factory=tuple)
    sandbox_code_root: str | None = None
    worktree_path: str | None = None
    active_execution_root: str | None = None
    worktree_isolation_active: bool = False
    recent_git_status: str = ""
    task_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkspaceVerificationJudgeResult:
    """Structured result returned by the verification judge agent."""

    verdict: WorkspaceVerificationJudgeVerdict
    rationale: str
    failed_criteria: tuple[str, ...] = field(default_factory=tuple)
    satisfied_guard_failures: tuple[str, ...] = field(default_factory=tuple)
    required_next_action: str = ""
    next_action_kind: WorkspaceVerificationNextActionKind = (
        WorkspaceVerificationNextActionKind.RETRY_SAME_NODE
    )
    repair_brief: dict[str, Any] = field(default_factory=dict)
    feedback_items: tuple[WorkspaceVerificationFeedbackItem, ...] = field(default_factory=tuple)
    confidence: float = 0.0

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("WorkspaceVerificationJudgeResult.confidence must be in [0,1]")


class WorkspaceVerificationJudgePort(Protocol):
    """Agent-First semantic adjudication boundary for workspace verification."""

    async def judge(
        self,
        request: WorkspaceVerificationJudgeRequest,
    ) -> WorkspaceVerificationJudgeResult: ...


__all__ = [
    "WorkspaceVerificationFeedbackItem",
    "WorkspaceVerificationFeedbackKind",
    "WorkspaceVerificationFeedbackSeverity",
    "WorkspaceVerificationFeedbackTargetLayer",
    "WorkspaceVerificationJudgePort",
    "WorkspaceVerificationJudgeRequest",
    "WorkspaceVerificationJudgeResult",
    "WorkspaceVerificationJudgeVerdict",
    "WorkspaceVerificationNextActionKind",
    "WorkspaceVerificationRecommendedAction",
]
