"""Durable controller for autonomous workspace plan progression."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttemptStatus,
)
from src.domain.model.workspace_plan import Plan, PlanStatus, TaskIntent
from src.domain.ports.services.workspace_supervisor_port import TickReport
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    PlanModel,
    PlanNodeModel,
    WorkspaceModel,
    WorkspacePlanOutboxModel,
    WorkspaceTaskModel,
    WorkspaceTaskSessionAttemptModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_plan_repository import SqlPlanRepository
from src.infrastructure.agent.workspace_plan.factory import build_sql_orchestrator
from src.infrastructure.agent.workspace_plan.run_contract import WorkspaceRunContract

WorkspaceRunTickRunner = Callable[[], Awaitable[TickReport | None]]

_ACTIVE_OUTBOX_STATUSES = frozenset({"pending", "failed", "processing", "dead_letter"})
_ACTIVE_ATTEMPT_STATUSES = frozenset(
    {
        WorkspaceTaskSessionAttemptStatus.PENDING.value,
        WorkspaceTaskSessionAttemptStatus.RUNNING.value,
        WorkspaceTaskSessionAttemptStatus.AWAITING_LEADER_ADJUDICATION.value,
    }
)


@dataclass(frozen=True)
class WorkspaceRunTickResult:
    """Observable result of one controller tick."""

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
    """Single authoritative tick entrypoint for a workspace plan run."""

    _process_locks: ClassVar[dict[str, asyncio.Lock]] = {}
    _process_locks_guard: ClassVar[asyncio.Lock] = asyncio.Lock()

    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self._session = session

    async def tick(
        self,
        *,
        plan_id: str | None = None,
        workspace_id: str | None = None,
        reason: str,
        actor_id: str | None = None,
        runner: WorkspaceRunTickRunner | None = None,
        current_outbox_id: str | None = None,
    ) -> WorkspaceRunTickResult:
        """Run one durable progression tick under the plan/workspace lock."""

        if not plan_id and not workspace_id:
            raise ValueError("plan_id or workspace_id is required")

        lock_key = await self._lock_key(plan_id=plan_id, workspace_id=workspace_id)
        process_lock = await self._process_lock(lock_key)
        async with process_lock:
            return await self._tick_locked(
                plan_id=plan_id,
                workspace_id=workspace_id,
                reason=reason,
                actor_id=actor_id,
                runner=runner,
                current_outbox_id=current_outbox_id,
                lock_key=lock_key,
            )

    async def _tick_locked(
        self,
        *,
        plan_id: str | None,
        workspace_id: str | None,
        reason: str,
        actor_id: str | None,
        runner: WorkspaceRunTickRunner | None,
        current_outbox_id: str | None,
        lock_key: str,
    ) -> WorkspaceRunTickResult:
        started_at = datetime.now(UTC)
        locked_plan_id, resolved_workspace_id = await self._acquire_database_lock(
            plan_id=plan_id,
            workspace_id=workspace_id,
        )
        resolved_plan_id = locked_plan_id or plan_id
        if not resolved_workspace_id:
            raise ValueError("workspace_id could not be resolved for workspace run tick")

        plan = await self._load_plan(resolved_plan_id, resolved_workspace_id)
        contract = await self._resolve_contract(plan=plan, workspace_id=resolved_workspace_id)
        tick_report = await self._run_tick(
            workspace_id=resolved_workspace_id,
            runner=runner,
        )
        refreshed_plan = await self._load_plan(
            resolved_plan_id or (plan.id if plan else None),
            resolved_workspace_id,
        )
        retry_queue = await self.retry_queue(
            resolved_workspace_id,
            plan_id=resolved_plan_id,
            limit=50,
        )
        active_attempts = await self.active_attempts(
            resolved_workspace_id,
            plan_id=resolved_plan_id,
        )
        completion_gate = completion_gate_for_plan(
            refreshed_plan,
            retry_queue=retry_queue,
            active_attempts=active_attempts,
            contract=contract,
            current_outbox_id=current_outbox_id,
        )
        finished_at = datetime.now(UTC)
        last_reconciliation = {
            "reconciled_at": finished_at.isoformat(),
            "reason": reason,
            "actor_id": actor_id,
            "plan_id": refreshed_plan.id if refreshed_plan is not None else resolved_plan_id,
            "workspace_id": resolved_workspace_id,
        }
        controller_state = {
            "phase": "reconciled",
            "lock_key": lock_key,
            "plan_id": refreshed_plan.id if refreshed_plan is not None else resolved_plan_id,
            "workspace_id": resolved_workspace_id,
            "plan_status": refreshed_plan.status.value if refreshed_plan is not None else None,
            "retry_queue_count": len(retry_queue),
            "active_attempt_count": len(active_attempts),
            "completion_allowed": completion_gate["allowed"],
        }
        result = WorkspaceRunTickResult(
            plan_id=refreshed_plan.id if refreshed_plan is not None else resolved_plan_id,
            workspace_id=resolved_workspace_id,
            reason=reason,
            actor_id=actor_id,
            started_at=started_at,
            finished_at=finished_at,
            controller_state=controller_state,
            retry_queue=retry_queue,
            active_attempts=active_attempts,
            last_reconciliation=last_reconciliation,
            completion_gate=completion_gate,
            blocked_reason=_first_blocked_reason(completion_gate),
            contract=contract,
            tick_report=tick_report,
            errors=tuple(tick_report.errors) if tick_report else (),
        )
        return result

    async def _run_tick(
        self,
        *,
        workspace_id: str,
        runner: WorkspaceRunTickRunner | None,
    ) -> TickReport | None:
        if runner is not None:
            return await runner()
        orchestrator = build_sql_orchestrator(self._session)
        return await orchestrator.tick_once(workspace_id)

    async def _load_plan(self, plan_id: str | None, workspace_id: str) -> Plan | None:
        repo = SqlPlanRepository(self._session)
        if plan_id:
            return await repo.get(plan_id)
        return await repo.get_by_workspace(workspace_id)

    async def _resolve_contract(
        self,
        *,
        plan: Plan | None,
        workspace_id: str,
    ) -> WorkspaceRunContract:
        workspace = await self._session.get(WorkspaceModel, workspace_id)
        workspace_metadata = dict(workspace.metadata_json or {}) if workspace is not None else {}
        root_metadata: Mapping[str, Any] | None = None
        if plan is not None:
            try:
                root_metadata = plan.goal_node.metadata
            except ValueError:
                root_metadata = {}
        return WorkspaceRunContract.from_sources(
            workspace_metadata=workspace_metadata,
            root_metadata=root_metadata,
        )

    async def _acquire_database_lock(
        self,
        *,
        plan_id: str | None,
        workspace_id: str | None,
    ) -> tuple[str | None, str | None]:
        if plan_id:
            stmt = (
                select(PlanModel.id, PlanModel.workspace_id)
                .where(PlanModel.id == plan_id)
                .with_for_update()
            )
            result = await self._session.execute(refresh_select_statement(stmt))
            row = result.first()
            if row is not None:
                return str(row.id), str(row.workspace_id)
        if workspace_id:
            stmt = (
                select(PlanModel.id, PlanModel.workspace_id)
                .where(PlanModel.workspace_id == workspace_id)
                .order_by(PlanModel.created_at.desc(), PlanModel.id.desc())
                .limit(1)
                .with_for_update()
            )
            result = await self._session.execute(refresh_select_statement(stmt))
            row = result.first()
            if row is not None:
                return str(row.id), str(row.workspace_id)
            workspace_stmt = (
                select(WorkspaceModel.id).where(WorkspaceModel.id == workspace_id).with_for_update()
            )
            workspace_result = await self._session.execute(refresh_select_statement(workspace_stmt))
            workspace_row = workspace_result.first()
            if workspace_row is not None:
                return None, str(workspace_row.id)
        return plan_id, workspace_id

    async def retry_queue(
        self,
        workspace_id: str,
        *,
        plan_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(WorkspacePlanOutboxModel)
            .where(WorkspacePlanOutboxModel.workspace_id == workspace_id)
            .where(WorkspacePlanOutboxModel.status.in_(tuple(_ACTIVE_OUTBOX_STATUSES)))
        )
        if plan_id:
            stmt = stmt.where(WorkspacePlanOutboxModel.plan_id == plan_id)
        result = await self._session.execute(
            refresh_select_statement(
                stmt.order_by(
                    WorkspacePlanOutboxModel.created_at.asc(),
                    WorkspacePlanOutboxModel.id.asc(),
                ).limit(limit)
            )
        )
        return [_outbox_row(item) for item in result.scalars().all()]

    async def active_attempts(
        self,
        workspace_id: str,
        *,
        plan_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(WorkspaceTaskSessionAttemptModel)
            .join(
                WorkspaceTaskModel,
                WorkspaceTaskModel.id == WorkspaceTaskSessionAttemptModel.workspace_task_id,
            )
            .where(WorkspaceTaskSessionAttemptModel.workspace_id == workspace_id)
            .where(WorkspaceTaskSessionAttemptModel.status.in_(tuple(_ACTIVE_ATTEMPT_STATUSES)))
            .where(WorkspaceTaskModel.status.not_in(("done", "blocked")))
        )
        if plan_id:
            current_attempt_ids = (
                select(PlanNodeModel.current_attempt_id)
                .where(PlanNodeModel.plan_id == plan_id)
                .where(PlanNodeModel.current_attempt_id.is_not(None))
            )
            stmt = stmt.where(WorkspaceTaskSessionAttemptModel.id.in_(current_attempt_ids))
        result = await self._session.execute(
            refresh_select_statement(
                stmt.order_by(
                    WorkspaceTaskSessionAttemptModel.created_at.asc(),
                    WorkspaceTaskSessionAttemptModel.id.asc(),
                ).limit(limit)
            )
        )
        return [_attempt_row(item) for item in result.scalars().all()]

    @classmethod
    async def _process_lock(cls, lock_key: str) -> asyncio.Lock:
        async with cls._process_locks_guard:
            lock = cls._process_locks.get(lock_key)
            if lock is None:
                lock = asyncio.Lock()
                cls._process_locks[lock_key] = lock
            return lock

    async def _lock_key(self, *, plan_id: str | None, workspace_id: str | None) -> str:
        if plan_id:
            return f"plan:{plan_id}"
        return f"workspace:{workspace_id}"


def completion_gate_for_plan(
    plan: Plan | None,
    *,
    retry_queue: list[dict[str, Any]],
    active_attempts: list[dict[str, Any]],
    contract: WorkspaceRunContract,
    current_outbox_id: str | None = None,
) -> dict[str, Any]:
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


def _first_blocked_reason(completion_gate: Mapping[str, Any]) -> str | None:
    reasons = completion_gate.get("blocked_reasons")
    if isinstance(reasons, list) and reasons:
        return str(reasons[0])
    return None


def _outbox_row(item: WorkspacePlanOutboxModel) -> dict[str, Any]:
    return {
        "outbox_id": item.id,
        "plan_id": item.plan_id,
        "workspace_id": item.workspace_id,
        "event_type": item.event_type,
        "status": item.status,
        "attempt_count": item.attempt_count,
        "max_attempts": item.max_attempts,
        "lease_owner": item.lease_owner,
        "lease_expires_at": _datetime_iso(item.lease_expires_at),
        "next_attempt_at": _datetime_iso(item.next_attempt_at),
        "processed_at": _datetime_iso(item.processed_at),
        "created_at": _datetime_iso(item.created_at),
        "last_error": item.last_error,
        "payload": dict(item.payload_json or {}),
        "metadata": dict(item.metadata_json or {}),
    }


def _attempt_row(item: WorkspaceTaskSessionAttemptModel) -> dict[str, Any]:
    return {
        "attempt_id": item.id,
        "workspace_task_id": item.workspace_task_id,
        "root_goal_task_id": item.root_goal_task_id,
        "workspace_id": item.workspace_id,
        "attempt_number": item.attempt_number,
        "status": item.status,
        "conversation_id": item.conversation_id,
        "worker_agent_id": item.worker_agent_id,
        "leader_agent_id": item.leader_agent_id,
        "created_at": _datetime_iso(item.created_at),
        "updated_at": _datetime_iso(item.updated_at),
        "completed_at": _datetime_iso(item.completed_at),
    }


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


def _datetime_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


__all__ = [
    "WorkspaceRunController",
    "WorkspaceRunTickResult",
    "WorkspaceRunTickRunner",
    "completion_gate_for_plan",
]
