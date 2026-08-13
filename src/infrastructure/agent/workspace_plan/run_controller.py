"""Retired Python Plan controller plus side-effect-free completion checks.

Durable progression, retry queues, attempts, and locking now belong to Avernet
Workspace Core. The pure completion-gate helper remains reusable for snapshots
that Core has already materialized.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.domain.model.workspace_plan import Plan, PlanStatus, TaskIntent
from src.domain.ports.services.workspace_supervisor_port import TickReport
from src.infrastructure.agent.workspace_plan.run_contract import WorkspaceRunContract

WorkspaceRunTickRunner = Callable[[], Awaitable[TickReport | None]]


class LegacyWorkspacePlanRuntimeRetiredError(RuntimeError):
    """Raised when platform code tries to run the retired SQL controller."""


@dataclass(frozen=True)
class WorkspaceRunTickResult:
    """Historical result shape retained for import compatibility."""

    plan_id: str | None
    workspace_id: str
    reason: str
    actor_id: str | None
    started_at: datetime
    finished_at: datetime
    controller_state: dict[str, Any]
    retry_queue: list[dict[str, Any]]
    active_attempts: list[dict[str, Any]]
    last_reconciliation: dict[str, Any]
    completion_gate: dict[str, Any]
    blocked_reason: str | None
    contract: WorkspaceRunContract
    tick_report: TickReport | None = None
    errors: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "workspace_id": self.workspace_id,
            "reason": self.reason,
            "actor_id": self.actor_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "controller_state": dict(self.controller_state),
            "retry_queue": [dict(item) for item in self.retry_queue],
            "active_attempts": [dict(item) for item in self.active_attempts],
            "last_reconciliation": dict(self.last_reconciliation),
            "completion_gate": dict(self.completion_gate),
            "blocked_reason": self.blocked_reason,
            "contract": self.contract.to_dict(),
            "tick_report": _tick_report_to_dict(self.tick_report),
            "errors": list(self.errors),
        }


class WorkspaceRunController:
    """Fail-closed compatibility shell for the retired Python controller."""

    def __init__(self, session: object) -> None:
        self._session = session

    async def tick(self, **_kwargs: object) -> WorkspaceRunTickResult:
        raise LegacyWorkspacePlanRuntimeRetiredError(
            "Python Workspace Plan controller is retired; use Avernet Workspace Core"
        )

    async def retry_queue(self, *_args: object, **_kwargs: object) -> list[dict[str, Any]]:
        raise LegacyWorkspacePlanRuntimeRetiredError(
            "Python Workspace Plan retry queue is retired; use Avernet Workspace Core"
        )

    async def active_attempts(self, *_args: object, **_kwargs: object) -> list[dict[str, Any]]:
        raise LegacyWorkspacePlanRuntimeRetiredError(
            "Python Workspace Plan attempt authority is retired; use Avernet Workspace Core"
        )


def completion_gate_for_plan(
    plan: Plan | None,
    *,
    retry_queue: list[dict[str, Any]],
    active_attempts: list[dict[str, Any]],
    contract: WorkspaceRunContract,
    current_outbox_id: str | None = None,
) -> dict[str, Any]:
    """Evaluate an already-materialized snapshot without reading persistence."""
    retry_blockers = [item for item in retry_queue if item.get("outbox_id") != current_outbox_id]
    evidence_gaps = _completion_evidence_gaps(plan, contract)
    worktree_gaps = _completion_worktree_integration_gaps(plan)
    checks = {
        "plan_completed": plan is not None and plan.status is PlanStatus.COMPLETED,
        "no_active_retry_outbox": not retry_blockers,
        "no_running_attempts": not active_attempts,
        "evidence_satisfied": not evidence_gaps,
        "worktrees_integrated": not worktree_gaps,
    }
    blocked_reasons: list[str] = []
    if plan is None:
        blocked_reasons.append("no active plan")
    elif not checks["plan_completed"]:
        blocked_reasons.append(f"plan status is {plan.status.value}")
    if retry_blockers:
        blocked_reasons.append("active or retryable outbox items remain")
    if active_attempts:
        blocked_reasons.append("running workspace task attempts remain")
    if evidence_gaps:
        blocked_reasons.append("required acceptance criteria lack verifier evidence")
    if worktree_gaps:
        blocked_reasons.append("accepted worktree integration is incomplete")
    return {
        "allowed": all(checks.values()),
        "checks": checks,
        "blocked_reasons": blocked_reasons,
        "required_evidence_gaps": evidence_gaps,
        "worktree_integration_gaps": worktree_gaps,
    }


def _completion_evidence_gaps(
    plan: Plan | None,
    contract: WorkspaceRunContract,
) -> list[dict[str, Any]]:
    if plan is None or contract.completion_evidence_policy == "none":
        return []
    gaps: list[dict[str, Any]] = []
    for node in plan.nodes.values():
        required_criteria = [item for item in node.acceptance_criteria if item.required]
        if not required_criteria and contract.completion_evidence_policy != "any_verifier_evidence":
            continue
        metadata = dict(node.metadata or {})
        has_evidence = bool(metadata.get("verification_evidence_refs")) or bool(
            metadata.get("last_verification_summary")
        )
        passed = metadata.get("last_verification_passed") is True
        if node.intent is TaskIntent.DONE and passed and has_evidence:
            continue
        gaps.append(
            {
                "node_id": node.id,
                "workspace_task_id": node.workspace_task_id,
                "title": node.title,
                "required_criteria_count": len(required_criteria),
                "last_verification_passed": metadata.get("last_verification_passed"),
                "reason": "missing verifier evidence for required acceptance criteria",
            }
        )
    return gaps


_SUCCESSFUL_WORKTREE_INTEGRATION_STATUSES = frozenset({"merged", "already_merged", "skipped"})
_BLOCKING_WORKTREE_INTEGRATION_STATUSES = frozenset({"blocked_dirty_main", "failed"})


def _completion_worktree_integration_gaps(plan: Plan | None) -> list[dict[str, Any]]:
    if plan is None:
        return []
    gaps: list[dict[str, Any]] = []
    for node in plan.nodes.values():
        if node.intent is not TaskIntent.DONE:
            continue
        metadata = dict(node.metadata or {})
        status = _metadata_text(metadata.get("worktree_integration_status"))
        worktree_path = (
            _metadata_text(metadata.get("worktree_integration_worktree_path"))
            or _metadata_text(metadata.get("active_execution_root"))
            or _metadata_text(metadata.get("worktree_path"))
        )
        if not worktree_path and node.feature_checkpoint is not None:
            worktree_path = node.feature_checkpoint.worktree_path
        commit_ref = _metadata_text(metadata.get("verified_commit_ref")) or _metadata_text(
            metadata.get("worktree_integration_commit_ref")
        )
        if not commit_ref and node.feature_checkpoint is not None:
            commit_ref = node.feature_checkpoint.commit_ref
        if status in _SUCCESSFUL_WORKTREE_INTEGRATION_STATUSES:
            continue
        if status in _BLOCKING_WORKTREE_INTEGRATION_STATUSES or (
            commit_ref and _looks_like_attempt_worktree(worktree_path)
        ):
            gaps.append(
                {
                    "node_id": node.id,
                    "workspace_task_id": node.workspace_task_id,
                    "title": node.title,
                    "attempt_id": metadata.get("worktree_integration_attempt_id")
                    or node.current_attempt_id,
                    "commit_ref": commit_ref,
                    "worktree_path": worktree_path,
                    "status": status or "missing",
                    "dirty_signature": metadata.get("worktree_integration_dirty_signature"),
                    "reason": "accepted attempt commit has not been integrated into main checkout",
                }
            )
    return gaps


def _looks_like_attempt_worktree(path: str | None) -> bool:
    return bool(path and "/.memstack/worktrees/" in path)


def _metadata_text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def _tick_report_to_dict(report: TickReport | None) -> dict[str, Any] | None:
    if report is None:
        return None
    return {
        "workspace_id": report.workspace_id,
        "allocations_made": report.allocations_made,
        "verifications_ran": report.verifications_ran,
        "nodes_completed": report.nodes_completed,
        "nodes_blocked": report.nodes_blocked,
        "errors": list(report.errors),
    }


__all__ = [
    "LegacyWorkspacePlanRuntimeRetiredError",
    "WorkspaceRunController",
    "WorkspaceRunTickResult",
    "WorkspaceRunTickRunner",
    "completion_gate_for_plan",
]
