"""Runtime bridge for workspace goal sensing/materialization."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from typing import Protocol

from src.application.schemas.workspace_agent_autonomy import AUTONOMY_SCHEMA_VERSION
from src.application.services.workspace_agent_autonomy import (
    synthesize_goal_evidence_from_children,
    validate_autonomy_metadata,
)
from src.application.services.workspace_goal_materialization_service import (
    WorkspaceGoalMaterializationService,
)
from src.application.services.workspace_goal_sensing_service import WorkspaceGoalSensingService
from src.application.services.workspace_task_command_service import WorkspaceTaskCommandService
from src.application.services.workspace_task_event_publisher import (
    PendingWorkspaceTaskEvent,
    WorkspaceTaskEventPublisher,
    serialize_workspace_task,
)
from src.application.services.workspace_task_service import WorkspaceTaskService
from src.domain.events.types import AgentEventType
from src.domain.model.workspace.workspace_task import (
    WorkspaceTask,
    WorkspaceTaskPriority,
    WorkspaceTaskStatus,
)
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.sql_blackboard_repository import (
    SqlBlackboardRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_cyber_objective_repository import (
    SqlCyberObjectiveRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_agent_repository import (
    SqlWorkspaceAgentRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_member_repository import (
    SqlWorkspaceMemberRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_message_repository import (
    SqlWorkspaceMessageRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_repository import (
    SqlWorkspaceRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository import (
    SqlWorkspaceTaskRepository,
)
from src.infrastructure.agent.state.agent_worker_state import get_redis_client
from src.infrastructure.agent.subagent.task_decomposer import DecompositionResult

logger = logging.getLogger(__name__)
_MAX_AUTO_REPLAN_ATTEMPTS = 2
_WORKSPACE_AUTONOMY_INTENT = re.compile(
    (
        r"\b(workspace|goal|objective|task|tasks)\b.*"
        r"\b(autonomy|execute|execution|plan|decompose|complete|finish|break down)\b"
        r"|\b(autonomy|execute|execution|plan|decompose|complete|finish|break down)\b.*"
        r"\b(workspace|goal|objective|task|tasks)\b"
    ),
    re.IGNORECASE,
)
_WORKSPACE_TASK_ID_PATTERN = re.compile(
    r"(?:workspace_task_id|task_id|child_task_id)\s*[:=]\s*([A-Za-z0-9._-]+)",
    re.IGNORECASE,
)
_WORKER_TERMINAL_REPORT_TYPES = frozenset({"completed", "failed", "blocked", "needs_replan"})


def should_activate_workspace_authority(user_query: str) -> bool:
    return bool(_WORKSPACE_AUTONOMY_INTENT.search(user_query))


class TaskDecomposerProtocol(Protocol):
    async def decompose(self, query: str) -> DecompositionResult: ...


async def maybe_materialize_workspace_goal_candidate(
    project_id: str,
    tenant_id: str,
    user_id: str,
    *,
    leader_agent_id: str | None = None,
    task_decomposer: TaskDecomposerProtocol | None = None,
    user_query: str = "",
) -> WorkspaceTask | None:
    """Materialize the top sensed workspace goal candidate when applicable.

    This is a bounded runtime hook: it reuses the existing workspace ledger and
    candidate ranking logic, but it does not yet orchestrate decomposition or
    execution after materialization.
    """
    if not project_id or not tenant_id or not user_id:
        return None

    try:
        redis_client = await get_redis_client()
    except Exception:
        logger.warning("Workspace goal runtime: redis unavailable", exc_info=True)
        redis_client = None

    try:
        async with async_session_factory() as db:
            workspace_repo = SqlWorkspaceRepository(db)
            workspaces = await workspace_repo.find_by_project(
                tenant_id=tenant_id,
                project_id=project_id,
                limit=1,
            )
            if not workspaces:
                return None

            workspace = workspaces[0]
            task_repo = SqlWorkspaceTaskRepository(db)
            task_service = WorkspaceTaskService(
                workspace_repo=workspace_repo,
                workspace_member_repo=SqlWorkspaceMemberRepository(db),
                workspace_agent_repo=SqlWorkspaceAgentRepository(db),
                workspace_task_repo=task_repo,
            )
            tasks = await task_service.list_tasks(
                workspace_id=workspace.id,
                actor_user_id=user_id,
                limit=100,
                offset=0,
            )
            objectives = await SqlCyberObjectiveRepository(db).find_by_workspace(
                workspace.id,
                limit=50,
            )
            posts = await SqlBlackboardRepository(db).list_posts_by_workspace(
                workspace.id,
                limit=20,
            )
            messages = await SqlWorkspaceMessageRepository(db).find_by_workspace(
                workspace.id,
                limit=50,
            )

            candidates = WorkspaceGoalSensingService().sense_candidates(
                tasks=tasks,
                objectives=objectives,
                posts=posts,
                messages=messages,
            )
            if not candidates:
                return None
            extra_events: list[PendingWorkspaceTaskEvent] = []

            command_service = WorkspaceTaskCommandService(task_service)
            materializer = WorkspaceGoalMaterializationService(
                objective_repo=SqlCyberObjectiveRepository(db),
                task_repo=task_repo,
                task_service=task_service,
                task_command_service=command_service,
            )
            task = await materializer.materialize_candidate(
                workspace_id=workspace.id,
                actor_user_id=user_id,
                candidate=candidates[0],
            )
            if task is None:
                return None

            await _maybe_bootstrap_execution_tasks(
                workspace_id=workspace.id,
                actor_user_id=user_id,
                root_task=task,
                task_repo=task_repo,
                workspace_agent_repo=SqlWorkspaceAgentRepository(db),
                command_service=command_service,
                leader_agent_id=leader_agent_id,
                task_decomposer=task_decomposer,
                user_query=user_query,
            )
            task = await _maybe_handle_root_remediation(
                workspace_id=workspace.id,
                actor_user_id=user_id,
                root_task=task,
                task_repo=task_repo,
                workspace_agent_repo=SqlWorkspaceAgentRepository(db),
                command_service=command_service,
                leader_agent_id=leader_agent_id,
                task_decomposer=task_decomposer,
                user_query=user_query,
            )
            if getattr(task, "metadata", {}).get("task_role") == "goal_root":
                extra_events.append(
                    PendingWorkspaceTaskEvent(
                        workspace_id=workspace.id,
                        event_type=AgentEventType.WORKSPACE_TASK_UPDATED,
                        payload={"task": serialize_workspace_task(task)},
                    )
                )

            await db.commit()
            publisher = WorkspaceTaskEventPublisher(redis_client)
            await publisher.publish_pending_events(
                [*command_service.consume_pending_events(), *extra_events]
            )
            return task
    except Exception:
        logger.warning("Workspace goal runtime materialization failed", exc_info=True)
        return None


async def _maybe_handle_root_remediation(
    *,
    workspace_id: str,
    actor_user_id: str,
    root_task: WorkspaceTask,
    task_repo: SqlWorkspaceTaskRepository,
    workspace_agent_repo: SqlWorkspaceAgentRepository,
    command_service: WorkspaceTaskCommandService,
    leader_agent_id: str | None,
    task_decomposer: TaskDecomposerProtocol | None,
    user_query: str,
) -> WorkspaceTask:
    remediation_status = getattr(root_task, "metadata", {}).get("remediation_status")
    root_task_id = getattr(root_task, "id", None)
    if not isinstance(root_task_id, str) or not root_task_id:
        return root_task

    if remediation_status == "replan_required":
        attempts_raw = getattr(root_task, "metadata", {}).get("replan_attempt_count", 0)
        attempts = attempts_raw if isinstance(attempts_raw, int) and attempts_raw >= 0 else 0
        if attempts >= _MAX_AUTO_REPLAN_ATTEMPTS:
            await _mark_root_human_review_required(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                root_task=root_task,
                task_repo=task_repo,
                command_service=command_service,
                leader_agent_id=leader_agent_id,
            )
            refreshed = await task_repo.find_by_id(root_task_id)
            return refreshed or root_task
        await _replan_execution_tasks(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            root_task=root_task,
            task_repo=task_repo,
            workspace_agent_repo=workspace_agent_repo,
            command_service=command_service,
            leader_agent_id=leader_agent_id,
            task_decomposer=task_decomposer,
            user_query=user_query,
        )
        await _increment_root_replan_attempt(
            root_task=root_task,
            task_repo=task_repo,
            next_attempt_count=attempts + 1,
        )
        refreshed = await task_repo.find_by_id(root_task_id)
        return refreshed or root_task

    if remediation_status == "ready_for_completion" and root_task.status.value != "done":
        await _ensure_root_goal_evidence(
            root_task=root_task,
            task_repo=task_repo,
            generated_by_agent_id=str(actor_user_id),
        )
        refreshed = await task_repo.find_by_id(root_task_id)
        if refreshed is None:
            return root_task
        if refreshed.status.value == "todo":
            refreshed = await command_service.start_task(
                workspace_id=workspace_id,
                task_id=root_task_id,
                actor_user_id=actor_user_id,
                actor_type="agent",
                reason="workspace_goal_runtime.ready_for_completion.start_root",
            )
        completed = await command_service.complete_task(
            workspace_id=workspace_id,
            task_id=root_task_id,
            actor_user_id=actor_user_id,
            actor_type="agent",
            reason="workspace_goal_runtime.ready_for_completion",
        )
        return completed

    return root_task


async def _ensure_root_goal_evidence(
    *,
    root_task: WorkspaceTask,
    task_repo: SqlWorkspaceTaskRepository,
    generated_by_agent_id: str,
) -> None:
    metadata = dict(getattr(root_task, "metadata", {}) or {})
    if "goal_evidence" in metadata:
        return

    root_task_id = getattr(root_task, "id", None)
    workspace_id = getattr(root_task, "workspace_id", None)
    if not isinstance(root_task_id, str) or not isinstance(workspace_id, str):
        return

    child_tasks = await task_repo.find_by_root_goal_task_id(workspace_id, root_task_id)
    synthesized = synthesize_goal_evidence_from_children(
        root_task=root_task,
        child_tasks=child_tasks,
        generated_by_agent_id=generated_by_agent_id,
    )
    if synthesized is None:
        return

    metadata["goal_evidence"] = synthesized
    root_task.metadata = validate_autonomy_metadata(metadata)
    _ = await task_repo.save(root_task)


async def _increment_root_replan_attempt(
    *,
    root_task: WorkspaceTask,
    task_repo: SqlWorkspaceTaskRepository,
    next_attempt_count: int,
) -> None:
    refreshed_root = await task_repo.find_by_id(root_task.id)
    effective_root = refreshed_root or root_task
    metadata = dict(getattr(effective_root, "metadata", {}) or {})
    metadata.setdefault("autonomy_schema_version", AUTONOMY_SCHEMA_VERSION)
    metadata["replan_attempt_count"] = next_attempt_count
    metadata["last_replan_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    effective_root.metadata = validate_autonomy_metadata(metadata)
    _ = await task_repo.save(effective_root)


async def _ensure_root_task_started(
    *,
    workspace_id: str,
    root_task: WorkspaceTask,
    actor_user_id: str,
    command_service: WorkspaceTaskCommandService,
    leader_agent_id: str | None,
    reason: str,
) -> WorkspaceTask:
    status_value = getattr(
        getattr(root_task, "status", None), "value", getattr(root_task, "status", None)
    )
    root_task_id = getattr(root_task, "id", None)
    if not isinstance(root_task_id, str) or status_value != "todo":
        return root_task

    return await command_service.start_task(
        workspace_id=workspace_id,
        task_id=root_task_id,
        actor_user_id=actor_user_id,
        actor_type="agent",
        actor_agent_id=leader_agent_id,
        reason=reason,
    )


async def _mark_root_human_review_required(
    *,
    workspace_id: str,
    actor_user_id: str,
    root_task: WorkspaceTask,
    task_repo: SqlWorkspaceTaskRepository,
    command_service: WorkspaceTaskCommandService,
    leader_agent_id: str | None,
) -> None:
    refreshed_root = await task_repo.find_by_id(root_task.id)
    effective_root = refreshed_root or root_task
    metadata = dict(getattr(effective_root, "metadata", {}) or {})
    metadata.setdefault("autonomy_schema_version", AUTONOMY_SCHEMA_VERSION)
    attempts = metadata.get("replan_attempt_count", _MAX_AUTO_REPLAN_ATTEMPTS)
    metadata["remediation_summary"] = (
        f"Auto-replan limit reached after {attempts} attempts; root goal requires human review"
    )
    metadata["last_replan_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    effective_root.metadata = validate_autonomy_metadata(metadata)
    updated = await command_service.update_task(
        workspace_id=workspace_id,
        task_id=effective_root.id,
        actor_user_id=actor_user_id,
        metadata=effective_root.metadata,
        actor_type="agent",
        actor_agent_id=leader_agent_id,
        reason="workspace_goal_runtime.human_review_required.metadata",
    )
    updated_status = getattr(
        getattr(updated, "status", None), "value", getattr(updated, "status", None)
    )
    if updated_status != "blocked":
        _ = await command_service.block_task(
            workspace_id=workspace_id,
            task_id=effective_root.id,
            actor_user_id=actor_user_id,
            actor_type="agent",
            actor_agent_id=leader_agent_id,
            reason="workspace_goal_runtime.human_review_required.block",
        )


async def _maybe_bootstrap_execution_tasks(
    *,
    workspace_id: str,
    actor_user_id: str,
    root_task: WorkspaceTask,
    task_repo: SqlWorkspaceTaskRepository,
    workspace_agent_repo: SqlWorkspaceAgentRepository,
    command_service: WorkspaceTaskCommandService,
    leader_agent_id: str | None,
    task_decomposer: TaskDecomposerProtocol | None,
    user_query: str,
) -> None:
    root_task_id = getattr(root_task, "id", None)
    root_title = getattr(root_task, "title", "")
    if not isinstance(root_task_id, str) or not root_task_id:
        return

    remediation_status = getattr(root_task, "metadata", {}).get("remediation_status")
    if remediation_status in {"replan_required", "ready_for_completion"}:
        return

    existing_children = await task_repo.find_by_root_goal_task_id(workspace_id, root_task_id)
    if existing_children:
        return

    decomposed_steps = await _decompose_root_goal(
        task_decomposer=task_decomposer,
        root_title=root_title or user_query,
        user_query=user_query,
    )
    created_tasks: list[WorkspaceTask] = []
    for index, (step_id, description) in enumerate(decomposed_steps, start=1):
        created_tasks.append(
            await command_service.create_task(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                title=description,
                metadata={
                    "autonomy_schema_version": 1,
                    "task_role": "execution_task",
                    "root_goal_task_id": root_task_id,
                    "lineage_source": "agent",
                    "derived_from_internal_plan_step": step_id or f"bootstrap-{index}",
                    "execution_state": _build_execution_state(
                        phase="todo",
                        reason="workspace_goal_runtime.bootstrap_execution_tasks",
                        action="created",
                        actor_id=leader_agent_id or actor_user_id,
                    ),
                },
                actor_type="agent",
                reason="workspace_goal_runtime.bootstrap_execution_tasks",
            )
        )
    await _assign_execution_tasks_to_workers(
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        created_tasks=created_tasks,
        workspace_agent_repo=workspace_agent_repo,
        command_service=command_service,
        leader_agent_id=leader_agent_id,
        reason="workspace_goal_runtime.bootstrap_assign_execution_tasks",
    )
    if created_tasks:
        _ = await _ensure_root_task_started(
            workspace_id=workspace_id,
            root_task=root_task,
            actor_user_id=actor_user_id,
            command_service=command_service,
            leader_agent_id=leader_agent_id,
            reason="workspace_goal_runtime.bootstrap_execution_tasks.start_root",
        )


async def _replan_execution_tasks(
    *,
    workspace_id: str,
    actor_user_id: str,
    root_task: WorkspaceTask,
    task_repo: SqlWorkspaceTaskRepository,
    workspace_agent_repo: SqlWorkspaceAgentRepository,
    command_service: WorkspaceTaskCommandService,
    leader_agent_id: str | None,
    task_decomposer: TaskDecomposerProtocol | None,
    user_query: str,
) -> None:
    root_task_id = getattr(root_task, "id", None)
    root_title = getattr(root_task, "title", "")
    if not isinstance(root_task_id, str) or not root_task_id:
        return

    existing_children = await task_repo.find_by_root_goal_task_id(workspace_id, root_task_id)
    for child in existing_children:
        _ = await command_service.delete_task(
            workspace_id=workspace_id,
            task_id=child.id,
            actor_user_id=actor_user_id,
        )

    decomposed_steps = await _decompose_root_goal(
        task_decomposer=task_decomposer,
        root_title=root_title or user_query,
        user_query=user_query,
    )
    created_tasks: list[WorkspaceTask] = []
    for index, (step_id, description) in enumerate(decomposed_steps, start=1):
        created_tasks.append(
            await command_service.create_task(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                title=description,
                metadata={
                    "autonomy_schema_version": 1,
                    "task_role": "execution_task",
                    "root_goal_task_id": root_task_id,
                    "lineage_source": "agent",
                    "derived_from_internal_plan_step": step_id or f"replan-{index}",
                    "execution_state": _build_execution_state(
                        phase="todo",
                        reason="workspace_goal_runtime.replan_execution_tasks",
                        action="created",
                        actor_id=leader_agent_id or actor_user_id,
                    ),
                },
                actor_type="agent",
                reason="workspace_goal_runtime.replan_execution_tasks",
            )
        )
    await _assign_execution_tasks_to_workers(
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        created_tasks=created_tasks,
        workspace_agent_repo=workspace_agent_repo,
        command_service=command_service,
        leader_agent_id=leader_agent_id,
        reason="workspace_goal_runtime.replan_assign_execution_tasks",
    )


def _build_execution_state(
    *,
    phase: str,
    reason: str,
    action: str,
    actor_id: str,
) -> dict[str, str]:
    return {
        "phase": phase,
        "last_agent_reason": reason,
        "last_agent_action": action,
        "updated_by_actor_type": "agent",
        "updated_by_actor_id": actor_id,
        "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def _parse_worker_report_payload(
    *,
    report_type: str,
    summary: str,
    artifacts: list[str],
) -> tuple[str, list[str], list[str]]:
    normalized_summary = summary.strip() or f"worker_report:{report_type}"
    merged_artifacts = list(dict.fromkeys(artifacts))
    verifications: list[str] = []

    try:
        payload = json.loads(summary)
    except Exception:
        payload = None

    if isinstance(payload, dict):
        payload_summary = payload.get("summary")
        if isinstance(payload_summary, str) and payload_summary.strip():
            normalized_summary = payload_summary.strip()
        payload_artifacts = payload.get("artifacts")
        if isinstance(payload_artifacts, list):
            merged_artifacts = list(
                dict.fromkeys(
                    [*merged_artifacts, *[str(item) for item in payload_artifacts if item]]
                )
            )
        payload_verifications = payload.get("verifications")
        if isinstance(payload_verifications, list):
            verifications.extend(str(item) for item in payload_verifications if item)
        verdict = payload.get("verdict") or payload.get("outcome")
        if isinstance(verdict, str) and verdict.strip():
            verifications.append(f"worker_verdict:{verdict.strip()}")
        verification_grade = payload.get("verification_grade")
        if isinstance(verification_grade, str) and verification_grade.strip():
            verifications.append(f"verification_grade:{verification_grade.strip()}")

    if report_type == "completed" and not verifications:
        verifications.append("worker_report:completed")

    return normalized_summary, merged_artifacts, list(dict.fromkeys(verifications))


def _build_worker_report_fingerprint(
    *,
    report_type: str,
    summary: str,
    artifacts: list[str],
    verifications: list[str],
    report_id: str | None,
) -> str:
    payload = {
        "report_id": report_id or "",
        "report_type": report_type,
        "summary": summary,
        "artifacts": list(artifacts),
        "verifications": list(verifications),
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


async def _assign_execution_tasks_to_workers(
    *,
    workspace_id: str,
    actor_user_id: str,
    created_tasks: list[WorkspaceTask],
    workspace_agent_repo: SqlWorkspaceAgentRepository,
    command_service: WorkspaceTaskCommandService,
    leader_agent_id: str | None,
    reason: str,
) -> None:
    if not created_tasks or not leader_agent_id:
        return

    active_bindings = await workspace_agent_repo.find_by_workspace(
        workspace_id=workspace_id,
        active_only=True,
        limit=100,
        offset=0,
    )
    if not active_bindings:
        return

    worker_bindings = [
        binding for binding in active_bindings if binding.agent_id != leader_agent_id
    ]
    if not worker_bindings:
        worker_bindings = list(active_bindings)
    if not worker_bindings:
        return

    worker_bindings.sort(
        key=lambda binding: (
            binding.display_name or "",
            binding.label or "",
            binding.agent_id,
            binding.id,
        )
    )

    for index, task in enumerate(created_tasks):
        binding = worker_bindings[index % len(worker_bindings)]
        _ = await command_service.assign_task_to_agent(
            workspace_id=workspace_id,
            task_id=task.id,
            actor_user_id=actor_user_id,
            workspace_agent_id=binding.id,
            actor_type="agent",
            actor_agent_id=leader_agent_id,
            reason=reason,
        )


async def apply_workspace_worker_report(  # noqa: PLR0915
    *,
    workspace_id: str,
    root_goal_task_id: str,
    task_id: str,
    actor_user_id: str,
    worker_agent_id: str | None,
    report_type: str,
    summary: str,
    artifacts: list[str] | None = None,
    leader_agent_id: str | None = None,
    report_id: str | None = None,
) -> WorkspaceTask | None:
    """Record a worker execution report as candidate evidence for later leader adjudication."""
    artifacts = [artifact for artifact in (artifacts or []) if artifact]
    try:
        async with async_session_factory() as db:
            workspace_repo = SqlWorkspaceRepository(db)
            task_repo = SqlWorkspaceTaskRepository(db)
            task_service = WorkspaceTaskService(
                workspace_repo=workspace_repo,
                workspace_member_repo=SqlWorkspaceMemberRepository(db),
                workspace_agent_repo=SqlWorkspaceAgentRepository(db),
                workspace_task_repo=task_repo,
            )
            command_service = WorkspaceTaskCommandService(task_service)

            task = await task_service.get_task(
                workspace_id=workspace_id,
                task_id=task_id,
                actor_user_id=actor_user_id,
            )
            if task.metadata.get("root_goal_task_id") != root_goal_task_id:
                raise ValueError("Worker report task does not belong to the provided root goal")
            if worker_agent_id is not None and task.assignee_agent_id != worker_agent_id:
                raise ValueError("Worker report does not match the task assignee")

            metadata = dict(task.metadata)
            evidence_refs = metadata.get("evidence_refs")
            if isinstance(evidence_refs, list):
                prior_refs = [str(ref) for ref in evidence_refs if ref]
                merged_artifacts = list(dict.fromkeys([*prior_refs, *artifacts]))
            else:
                merged_artifacts = list(dict.fromkeys(artifacts))
            existing_verifications = metadata.get("execution_verifications")
            if isinstance(existing_verifications, list):
                prior_verifications = [str(item) for item in existing_verifications if item]
            else:
                prior_verifications = []
            normalized_summary, merged_artifacts, report_verifications = (
                _parse_worker_report_payload(
                    report_type=report_type,
                    summary=summary,
                    artifacts=merged_artifacts,
                )
            )
            report_fingerprint = _build_worker_report_fingerprint(
                report_type=report_type,
                summary=normalized_summary,
                artifacts=merged_artifacts,
                verifications=report_verifications,
                report_id=report_id,
            )
            if metadata.get("last_worker_report_fingerprint") == report_fingerprint:
                return task
            metadata["evidence_refs"] = merged_artifacts
            metadata["execution_verifications"] = list(
                dict.fromkeys([*prior_verifications, *report_verifications])
            )
            reported_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
            pending_adjudication = report_type in _WORKER_TERMINAL_REPORT_TYPES
            metadata["last_worker_report_type"] = report_type
            metadata["last_worker_report_summary"] = normalized_summary
            metadata["last_worker_report_artifacts"] = list(merged_artifacts)
            metadata["last_worker_report_verifications"] = list(
                dict.fromkeys(report_verifications)
            )
            metadata["last_worker_reported_at"] = reported_at
            metadata["last_worker_report_fingerprint"] = report_fingerprint
            metadata["pending_leader_adjudication"] = pending_adjudication
            if report_id:
                metadata["last_worker_report_id"] = report_id
            phase = "pending_adjudication" if pending_adjudication else "in_progress"
            action = "await_leader_adjudication" if pending_adjudication else "start"
            metadata["execution_state"] = _build_execution_state(
                phase=phase,
                reason=f"workspace_goal_runtime.worker_report.{report_type}:{normalized_summary}",
                action=action,
                actor_id=leader_agent_id or actor_user_id,
            )

            updated = await command_service.update_task(
                workspace_id=workspace_id,
                task_id=task_id,
                actor_user_id=actor_user_id,
                metadata=metadata,
                blocker_reason=None,
                actor_type="agent",
                actor_agent_id=leader_agent_id,
                reason=f"workspace_goal_runtime.worker_report.{report_type}.metadata",
            )

            if updated.status.value == "todo":
                updated = await command_service.start_task(
                    workspace_id=workspace_id,
                    task_id=task_id,
                    actor_user_id=actor_user_id,
                    actor_type="agent",
                    actor_agent_id=leader_agent_id,
                    reason=f"workspace_goal_runtime.worker_report.{report_type}.start",
                )

            await db.commit()
            publisher = WorkspaceTaskEventPublisher(await get_redis_client())
            await publisher.publish_pending_events(command_service.consume_pending_events())
            return updated
    except Exception:
        logger.warning("Workspace worker report application failed", exc_info=True)
        return None


async def adjudicate_workspace_worker_report(
    *,
    workspace_id: str,
    task_id: str,
    actor_user_id: str,
    status: WorkspaceTaskStatus,
    leader_agent_id: str | None = None,
    title: str | None = None,
    priority: WorkspaceTaskPriority | None = None,
) -> WorkspaceTask | None:
    """Apply a leader decision to a previously ingested worker report."""
    try:
        async with async_session_factory() as db:
            workspace_repo = SqlWorkspaceRepository(db)
            task_repo = SqlWorkspaceTaskRepository(db)
            task_service = WorkspaceTaskService(
                workspace_repo=workspace_repo,
                workspace_member_repo=SqlWorkspaceMemberRepository(db),
                workspace_agent_repo=SqlWorkspaceAgentRepository(db),
                workspace_task_repo=task_repo,
            )
            command_service = WorkspaceTaskCommandService(task_service)

            task = await task_service.get_task(
                workspace_id=workspace_id,
                task_id=task_id,
                actor_user_id=actor_user_id,
            )
            metadata = dict(task.metadata)
            summary = str(metadata.get("last_worker_report_summary") or "").strip()
            if metadata.get("pending_leader_adjudication") is True:
                metadata["pending_leader_adjudication"] = False
            metadata["last_leader_adjudication_status"] = status.value
            metadata["last_leader_adjudicated_at"] = datetime.now(UTC).isoformat().replace(
                "+00:00",
                "Z",
            )
            phase_map = {
                WorkspaceTaskStatus.TODO: "todo",
                WorkspaceTaskStatus.IN_PROGRESS: "in_progress",
                WorkspaceTaskStatus.BLOCKED: "blocked",
                WorkspaceTaskStatus.DONE: "done",
            }
            action_map = {
                WorkspaceTaskStatus.TODO: "reprioritized",
                WorkspaceTaskStatus.IN_PROGRESS: "start",
                WorkspaceTaskStatus.BLOCKED: "blocked",
                WorkspaceTaskStatus.DONE: "completed",
            }
            metadata["execution_state"] = _build_execution_state(
                phase=phase_map[status],
                reason=f"workspace_goal_runtime.leader_adjudication.{status.value}:{summary or task.title}",
                action=action_map[status],
                actor_id=leader_agent_id or actor_user_id,
            )

            updated = await command_service.update_task(
                workspace_id=workspace_id,
                task_id=task_id,
                actor_user_id=actor_user_id,
                title=title,
                priority=priority,
                metadata=metadata,
                actor_type="agent",
                actor_agent_id=leader_agent_id,
                reason=f"workspace_goal_runtime.leader_adjudication.{status.value}.metadata",
            )
            if status == WorkspaceTaskStatus.IN_PROGRESS and updated.status.value == "todo":
                updated = await command_service.start_task(
                    workspace_id=workspace_id,
                    task_id=task_id,
                    actor_user_id=actor_user_id,
                    actor_type="agent",
                    actor_agent_id=leader_agent_id,
                    reason="workspace_goal_runtime.leader_adjudication.in_progress.start",
                )
            elif status == WorkspaceTaskStatus.DONE and updated.status.value != "done":
                updated = await command_service.complete_task(
                    workspace_id=workspace_id,
                    task_id=task_id,
                    actor_user_id=actor_user_id,
                    actor_type="agent",
                    actor_agent_id=leader_agent_id,
                    reason="workspace_goal_runtime.leader_adjudication.completed.complete",
                )
            elif status == WorkspaceTaskStatus.BLOCKED and updated.status.value != "blocked":
                updated = await command_service.block_task(
                    workspace_id=workspace_id,
                    task_id=task_id,
                    actor_user_id=actor_user_id,
                    actor_type="agent",
                    actor_agent_id=leader_agent_id,
                    reason="workspace_goal_runtime.leader_adjudication.blocked.block",
                )

            await db.commit()
            publisher = WorkspaceTaskEventPublisher(await get_redis_client())
            await publisher.publish_pending_events(command_service.consume_pending_events())
            return updated
    except Exception:
        logger.warning("Workspace worker report adjudication failed", exc_info=True)
        return None


async def resolve_workspace_execution_task_for_delegate(
    *,
    workspace_id: str,
    root_goal_task_id: str,
    delegated_task_text: str,
    subagent_name: str,
    workspace_task_id: str | None = None,
) -> WorkspaceTask | None:
    """Resolve a workspace execution task that best matches a delegated subagent task."""
    normalized_text = delegated_task_text.strip()
    explicit_task_id = workspace_task_id or _extract_workspace_task_id(normalized_text)
    try:
        async with async_session_factory() as db:
            task_repo = SqlWorkspaceTaskRepository(db)
            if explicit_task_id:
                task = await task_repo.find_by_id(explicit_task_id)
                if (
                    task is not None
                    and task.workspace_id == workspace_id
                    and task.metadata.get("root_goal_task_id") == root_goal_task_id
                ):
                    return task

            candidates = await task_repo.find_by_root_goal_task_id(workspace_id, root_goal_task_id)
            open_candidates = [
                task for task in candidates if task.status != WorkspaceTaskStatus.DONE
            ]
            if not open_candidates:
                return None

            exact_title_matches = [
                task
                for task in open_candidates
                if task.title.strip().lower() == normalized_text.lower()
            ]
            if len(exact_title_matches) == 1:
                return exact_title_matches[0]

            tagged_matches = [
                task
                for task in open_candidates
                if task.metadata.get("delegated_subagent_name") == subagent_name
                and task.title.strip().lower() == normalized_text.lower()
            ]
            if tagged_matches:
                return tagged_matches[0]

            if len(open_candidates) == 1:
                return open_candidates[0]
    except Exception:
        logger.warning("Workspace delegation task resolution failed", exc_info=True)
    return None


async def prepare_workspace_subagent_delegation(
    *,
    workspace_id: str,
    root_goal_task_id: str,
    actor_user_id: str,
    delegated_task_text: str,
    subagent_name: str,
    subagent_id: str | None,
    leader_agent_id: str | None,
    workspace_task_id: str | None = None,
) -> dict[str, str] | None:
    """Bind a delegated subagent run to a workspace task and mark it in progress via leader."""
    task = await resolve_workspace_execution_task_for_delegate(
        workspace_id=workspace_id,
        root_goal_task_id=root_goal_task_id,
        delegated_task_text=delegated_task_text,
        subagent_name=subagent_name,
        workspace_task_id=workspace_task_id,
    )
    if task is None:
        return None

    try:
        async with async_session_factory() as db:
            task_service = WorkspaceTaskService(
                workspace_repo=SqlWorkspaceRepository(db),
                workspace_member_repo=SqlWorkspaceMemberRepository(db),
                workspace_agent_repo=SqlWorkspaceAgentRepository(db),
                workspace_task_repo=SqlWorkspaceTaskRepository(db),
            )
            command_service = WorkspaceTaskCommandService(task_service)

            metadata = dict(task.metadata)
            metadata["delegated_subagent_name"] = subagent_name
            if subagent_id:
                metadata["delegated_subagent_id"] = subagent_id
            metadata["delegated_task_text"] = delegated_task_text.strip()

            updated = await command_service.update_task(
                workspace_id=workspace_id,
                task_id=task.id,
                actor_user_id=actor_user_id,
                metadata=metadata,
                actor_type="agent",
                actor_agent_id=leader_agent_id,
                reason="workspace_goal_runtime.prepare_subagent_delegation.metadata",
            )
            if updated.status == WorkspaceTaskStatus.TODO:
                updated = await command_service.start_task(
                    workspace_id=workspace_id,
                    task_id=task.id,
                    actor_user_id=actor_user_id,
                    actor_type="agent",
                    actor_agent_id=leader_agent_id,
                    reason="workspace_goal_runtime.prepare_subagent_delegation.start",
                )
            root_task = await task_service.get_task(
                workspace_id=workspace_id,
                task_id=root_goal_task_id,
                actor_user_id=actor_user_id,
            )
            _ = await _ensure_root_task_started(
                workspace_id=workspace_id,
                root_task=root_task,
                actor_user_id=actor_user_id,
                command_service=command_service,
                leader_agent_id=leader_agent_id,
                reason="workspace_goal_runtime.prepare_subagent_delegation.start_root",
            )

            await db.commit()
            publisher = WorkspaceTaskEventPublisher(await get_redis_client())
            await publisher.publish_pending_events(command_service.consume_pending_events())
            return {
                "workspace_task_id": updated.id,
                "workspace_id": workspace_id,
                "root_goal_task_id": root_goal_task_id,
                "actor_user_id": actor_user_id,
                "leader_agent_id": leader_agent_id or "",
            }
    except Exception:
        logger.warning("Workspace subagent delegation preparation failed", exc_info=True)
        return None


def _extract_workspace_task_id(task_text: str) -> str | None:
    match = _WORKSPACE_TASK_ID_PATTERN.search(task_text)
    if match:
        return match.group(1)
    return None


async def _decompose_root_goal(
    *,
    task_decomposer: TaskDecomposerProtocol | None,
    root_title: str,
    user_query: str,
) -> list[tuple[str | None, str]]:
    query = user_query.strip() or root_title.strip()
    if not query:
        return []
    if task_decomposer is not None and hasattr(task_decomposer, "decompose"):
        try:
            result = await task_decomposer.decompose(query)
            if result.subtasks:
                return [
                    (subtask.id or None, subtask.description)
                    for subtask in result.subtasks
                    if subtask.description
                ]
        except Exception:
            logger.warning("Workspace goal runtime decomposition failed", exc_info=True)
    return [(None, f"Execute goal: {query}")]
