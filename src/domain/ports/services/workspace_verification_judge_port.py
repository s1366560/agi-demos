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


@dataclass(frozen=True)
class WorkspaceVerificationJudgeRequest:
    """Bounded context passed to the verification judge agent."""

    workspace_id: str
    node_id: str
    attempt_id: str | None
    node_title: str
    node_description: str
    acceptance_criteria: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    worker_summary: str = ""
    candidate_artifacts: tuple[str, ...] = field(default_factory=tuple)
    candidate_verifications: tuple[str, ...] = field(default_factory=tuple)
    task_evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    latest_verification_results: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    guard_failures: tuple[str, ...] = field(default_factory=tuple)
    sandbox_code_root: str | None = None
    worktree_path: str | None = None
    recent_git_status: str = ""
    task_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class WorkspaceVerificationJudgeResult:
    """Structured result returned by the verification judge agent."""

    verdict: WorkspaceVerificationJudgeVerdict
    rationale: str
    failed_criteria: tuple[str, ...] = field(default_factory=tuple)
    required_next_action: str = ""
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
    "WorkspaceVerificationJudgePort",
    "WorkspaceVerificationJudgeRequest",
    "WorkspaceVerificationJudgeResult",
    "WorkspaceVerificationJudgeVerdict",
]
