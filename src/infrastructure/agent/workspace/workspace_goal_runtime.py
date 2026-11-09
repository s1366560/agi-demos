"""Runtime bridge for workspace goal sensing/materialization."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import redis.asyncio as redis
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.workspace_agent_autonomy import (
    AUTONOMY_SCHEMA_VERSION,
    GoalCandidateRecordModel,
)
from src.application.services.workspace_agent_autonomy import (
    is_goal_root_task,
    select_root_progress_child_tasks,
    synthesize_goal_evidence_from_children,
    validate_autonomy_metadata,
)
from src.application.services.workspace_autonomy_profiles import evaluate_completion_evidence
from src.application.services.workspace_task_command_service import WorkspaceTaskCommandService
from src.application.services.workspace_task_event_publisher import (
    PendingWorkspaceTaskEvent,
    WorkspaceTaskEventPublisher,
)
from src.application.services.workspace_task_service import (
    WorkspaceTaskAuthorityContext,
)
from src.application.services.workspace_task_session_attempt_service import (
    WorkspaceTaskSessionAttemptService,
)
from src.domain.model.workspace.workspace_task import (
    WorkspaceTask,
    WorkspaceTaskPriority,
    WorkspaceTaskStatus,
)
from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttempt,
    WorkspaceTaskSessionAttemptStatus,
)
from src.domain.model.workspace_plan import Plan
from src.domain.model.workspace_plan.plan import PlanStatus
from src.domain.model.workspace_plan.plan_node import PlanNodeKind, TaskExecution, TaskIntent
from src.domain.ports.repositories import WorkspaceTaskRepository
from src.infrastructure.agent.workspace.dispatcher.retry_policy import DEFAULT_RETRY_POLICY
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    AUTONOMY_SCHEMA_VERSION_KEY,
    CURRENT_ATTEMPT_ID,
    REMEDIATION_STATUS,
    REMEDIATION_SUMMARY,
    ROOT_GOAL_TASK_ID,
)
from src.infrastructure.agent.workspace_plan.system_actor import persisted_attempt_leader_agent_id
from src.infrastructure.workspace_core.legacy_runtime import legacy_workspace_runtime_retired

__all__ = [
    "_active_plan_is_effectively_complete",
    "_effectively_complete_plan_tail_allows_root_completion",
]

logger = logging.getLogger(__name__)
_background_tasks: set[asyncio.Task[Any]] = set()
_RETRY_CONVERSATION_SOURCE = "workspace_retry_launch"
_RETRY_CONVERSATION_STAGE = "retry_leader"


def _current_workspace_goal_redis_client_v2() -> redis.Redis:
    """Resolve Redis from the generation pinned to this workspace operation."""
    from src.infrastructure.plugins.v2.agent_worker_runtime import (
        current_agent_worker_redis_client_v2,
    )

    return current_agent_worker_redis_client_v2()


async def _publish_workspace_goal_events_v2(
    events: Sequence[PendingWorkspaceTaskEvent],
) -> None:
    """Publish workspace goal effects through the pinned generation Redis."""
    publisher = WorkspaceTaskEventPublisher(_current_workspace_goal_redis_client_v2())
    await publisher.publish_pending_events(events)


_WORKSPACE_TASK_ID_PATTERN = re.compile(
    r"(?:workspace_task_id|task_id|child_task_id)\s*[:=]\s*([A-Za-z0-9._-]+)",
    re.IGNORECASE,
)
_WORKER_TERMINAL_REPORT_TYPES = frozenset({"completed", "failed", "blocked", "needs_replan"})
_ATTEMPT_TERMINAL_STATUSES = frozenset(
    {
        WorkspaceTaskSessionAttemptStatus.ACCEPTED.value,
        WorkspaceTaskSessionAttemptStatus.REJECTED.value,
        WorkspaceTaskSessionAttemptStatus.BLOCKED.value,
        WorkspaceTaskSessionAttemptStatus.CANCELLED.value,
    }
)


def should_activate_workspace_authority(
    user_query: str,  # reserved for future structured-signal use; never parsed
    *,
    has_workspace_binding: bool = False,
    has_open_root: bool = False,
) -> bool:
    """Return True when workspace-autonomy authority should activate.

    Agent-First iron rule (AGENTS.md): semantic verdicts must come from an
    agent tool-call, not from regex / keyword matching. Activation here is
    driven solely by **structural set-membership signals** the caller has
    already established:

    - ``has_workspace_binding``: the turn carries a ``[workspace-task-binding]``
      marker (structural payload field), meaning the caller/agent has
      explicitly scoped this turn to a workspace task.
    - ``has_open_root``: the workspace has at least one open root goal task
      (set-membership query against ``workspace_tasks``).

    ``user_query`` is intentionally **not** inspected for keywords. If the
    user expresses an unsolicited goal in chat, the sensing service's
    ``message_signal`` path (fixed by H2 to be agent-judged) materializes
    the candidate — not this gate.
    """
    return has_workspace_binding or has_open_root


def _select_existing_root_candidate(
    candidates: Sequence[GoalCandidateRecordModel],
    tasks: list[WorkspaceTask],
) -> GoalCandidateRecordModel | None:
    root_tasks = {
        task.id: task
        for task in tasks
        if is_goal_root_task(task)
        and task.archived_at is None
        and task.status != WorkspaceTaskStatus.DONE
    }
    ranked_candidates: list[tuple[GoalCandidateRecordModel, WorkspaceTask]] = []
    for candidate in candidates:
        decision = getattr(candidate, "decision", None)
        if decision != "adopt_existing_goal":
            continue
        source_refs = getattr(candidate, "source_refs", [])
        task_refs = [
            source_ref.split(":", 1)[1]
            for source_ref in source_refs
            if isinstance(source_ref, str)
            and source_ref.startswith("task:")
            and source_ref.split(":", 1)[1] in root_tasks
        ]
        if not task_refs:
            continue
        root_task = root_tasks[task_refs[0]]
        ranked_candidates.append((candidate, root_task))
    if not ranked_candidates:
        for candidate in candidates:
            decision = getattr(candidate, "decision", None)
            source_refs = getattr(candidate, "source_refs", [])
            if decision == "adopt_existing_goal" and any(
                isinstance(source_ref, str) and source_ref.startswith("task:")
                for source_ref in source_refs
            ):
                return candidate
        return None
    ranked_candidates.sort(key=lambda item: (item[1].id,))
    ranked_candidates.sort(
        key=lambda item: (item[1].created_at,),
        reverse=True,
    )
    ranked_candidates.sort(
        key=lambda item: (item[1].updated_at or item[1].created_at,),
        reverse=True,
    )
    ranked_candidates.sort(
        key=lambda item: (float(getattr(item[0], "freshness", 0.0)),),
        reverse=True,
    )
    ranked_candidates.sort(
        key=lambda item: (float(getattr(item[0], "urgency", 0.0)),),
        reverse=True,
    )
    ranked_candidates.sort(
        key=lambda item: (float(getattr(item[0], "evidence_strength", 0.0)),),
        reverse=True,
    )
    return ranked_candidates[0][0]


async def _user_preferred_language_from_db(db: AsyncSession, user_id: str | None) -> str | None:
    """Look up the stored preferred_language for a user. Returns None on any failure."""
    if not isinstance(user_id, str) or not user_id:
        return None
    try:
        from sqlalchemy import select

        from src.infrastructure.adapters.secondary.persistence.models import User as DBUser

        result = await db.execute(select(DBUser.preferred_language).where(DBUser.id == user_id))
        value = result.scalar_one_or_none()
        if isinstance(value, str) and value in {"en-US", "zh-CN"}:
            return value
    except Exception:
        logger.debug("workspace_goal_runtime._user_preferred_language_failed", exc_info=True)
    return None


async def maybe_materialize_workspace_goal_candidate(
    project_id: str,
    tenant_id: str,
    user_id: str,
    *,
    leader_agent_id: str | None = None,
    user_query: str = "",
    preferred_language: str | None = None,
) -> WorkspaceTask | None:
    """Materialize the top sensed workspace goal candidate when applicable.

    This is a bounded runtime hook: it reuses the existing workspace ledger and
    candidate ranking logic, then hands the materialized root goal to the durable
    V2 workspace plan. Decomposition and execution are no longer performed by
    this module.
    """
    legacy_workspace_runtime_retired("Workspace goal materialization")


async def _ensure_root_goal_evidence(
    *,
    root_task: WorkspaceTask,
    task_repo: WorkspaceTaskRepository,
    generated_by_agent_id: str,
) -> tuple[bool, str | None]:
    metadata = dict(getattr(root_task, "metadata", {}) or {})
    workspace_metadata = await _load_workspace_metadata_for_task(
        task_repo=task_repo,
        workspace_id=getattr(root_task, "workspace_id", None),
    )
    existing = metadata.get("goal_evidence")
    if isinstance(existing, Mapping):
        if _existing_goal_evidence_allows_completion(
            root_task=root_task,
            evidence=existing,
            workspace_metadata=workspace_metadata,
        ):
            return True, None
        # Stale or insufficient evidence: fall through and re-synthesize so
        # accepted child attempts can clear old blocked/failed metadata.

    root_task_id = getattr(root_task, "id", None)
    workspace_id = getattr(root_task, "workspace_id", None)
    if not isinstance(root_task_id, str) or not isinstance(workspace_id, str):
        return False, "root auto-complete cannot resolve root task/workspace id"

    child_tasks = await _load_current_root_progress_children(
        task_repo=task_repo,
        workspace_id=workspace_id,
        root_task_id=root_task_id,
    )
    synthesized = synthesize_goal_evidence_from_children(
        root_task=root_task,
        child_tasks=child_tasks,
        generated_by_agent_id=generated_by_agent_id,
        workspace_metadata=workspace_metadata,
    )
    if synthesized is None:
        return False, "root auto-complete evidence synthesis did not produce evidence"

    metadata["goal_evidence"] = synthesized
    root_task.metadata = validate_autonomy_metadata(metadata)
    _ = await task_repo.save(root_task)
    evaluation = evaluate_completion_evidence(
        root_metadata=getattr(root_task, "metadata", {}) or {},
        evidence=synthesized,
        workspace_metadata=workspace_metadata,
    )
    if not evaluation.allowed:
        return False, evaluation.reason or "root auto-complete evidence is insufficient"
    return True, None


async def _load_current_root_progress_children(
    *,
    task_repo: WorkspaceTaskRepository,
    workspace_id: str,
    root_task_id: str,
) -> list[WorkspaceTask]:
    """Load the child tasks that currently drive root-goal progress."""

    current_plan_children_loader = getattr(
        task_repo,
        "find_current_plan_children_by_root_goal_task_id",
        None,
    )
    if current_plan_children_loader is not None:
        maybe_current_plan_children: object = current_plan_children_loader(
            workspace_id, root_task_id
        )
        current_plan_children: object = []
        if inspect.isawaitable(maybe_current_plan_children):
            current_plan_children = await maybe_current_plan_children
        if isinstance(current_plan_children, list):
            typed_current_plan_children = [
                child for child in current_plan_children if isinstance(child, WorkspaceTask)
            ]
            if typed_current_plan_children:
                return typed_current_plan_children
    return select_root_progress_child_tasks(
        await task_repo.find_by_root_goal_task_id(workspace_id, root_task_id)
    )


def _existing_goal_evidence_allows_completion(
    *,
    root_task: WorkspaceTask,
    evidence: Mapping[str, Any],
    workspace_metadata: Mapping[str, Any] | None,
) -> bool:
    try:
        evaluation = evaluate_completion_evidence(
            root_metadata=getattr(root_task, "metadata", {}) or {},
            evidence=evidence,
            workspace_metadata=workspace_metadata,
        )
    except Exception:
        return False
    return evaluation.allowed


async def _load_workspace_metadata_for_task(
    *,
    task_repo: WorkspaceTaskRepository,
    workspace_id: object,
) -> dict[str, Any]:
    if not isinstance(workspace_id, str) or not workspace_id:
        return {}
    session = getattr(task_repo, "_session", None)
    if session is None:
        return {}
    try:
        legacy_workspace_runtime_retired("workspace metadata")
    except Exception:
        logger.warning("workspace_goal_runtime.load_workspace_metadata_failed", exc_info=True)
        return {}


async def _workspace_run_gate_allows_root_completion(
    *,
    workspace_id: str,
    task_repo: WorkspaceTaskRepository,
) -> tuple[bool, str | None]:
    """Do not consult retired Workspace Plan SQL when evaluating Core-owned work."""
    _ = (workspace_id, task_repo)
    return True, None


def _active_plan_is_effectively_complete(plan: Plan) -> bool:
    if plan.status is not PlanStatus.ACTIVE:
        return False

    saw_non_goal_node = False
    for node in plan.nodes.values():
        if node.node_id == plan.goal_id or node.kind is PlanNodeKind.GOAL:
            continue
        saw_non_goal_node = True
        if node.intent is not TaskIntent.DONE:
            return False
        if node.execution is not TaskExecution.IDLE:
            return False
    return saw_non_goal_node


def _effectively_complete_plan_tail_allows_root_completion(
    *,
    plan: Plan,
    gate: Mapping[str, Any],
    retry_queue: Sequence[Mapping[str, Any]],
    active_attempts: Sequence[Mapping[str, Any]],
) -> bool:
    if not _active_plan_is_effectively_complete(plan):
        return False
    if active_attempts:
        return False

    non_tick_retry = [
        item
        for item in retry_queue
        if item.get("event_type") != "supervisor_tick" or item.get("status") != "processing"
    ]
    if non_tick_retry:
        return False

    reasons = gate.get("blocked_reasons")
    if not isinstance(reasons, list) or not reasons:
        return False
    allowed_tail_reasons = {
        "plan status is active",
        "active or retryable outbox items remain",
        "required acceptance criteria lack verifier evidence",
        "accepted worktree integration is incomplete",
    }
    return all(str(reason) in allowed_tail_reasons for reason in reasons)


async def _record_root_auto_complete_failure(
    *,
    root_task: WorkspaceTask,
    task_repo: WorkspaceTaskRepository,
    reason: str,
) -> None:
    try:
        refreshed = await task_repo.find_by_id(root_task.id)
        effective_root = refreshed or root_task
        metadata = dict(getattr(effective_root, "metadata", {}) or {})
        metadata.setdefault(AUTONOMY_SCHEMA_VERSION_KEY, AUTONOMY_SCHEMA_VERSION)
        metadata[REMEDIATION_STATUS] = "ready_for_completion"
        metadata[REMEDIATION_SUMMARY] = reason
        effective_root.metadata = validate_autonomy_metadata(metadata)
        _ = await task_repo.save(effective_root)
    except Exception:
        logger.warning(
            "auto_complete_ready_root: record failure reason failed",
            exc_info=True,
        )


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
        authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
    )


async def auto_complete_ready_root(
    *,
    workspace_id: str,
    actor_user_id: str,
    root_task: WorkspaceTask,
    task_repo: WorkspaceTaskRepository,
    command_service: WorkspaceTaskCommandService,
    leader_agent_id: str | None,
) -> WorkspaceTask | None:
    """Complete the root goal task when all its execution children are DONE.

    Returns the updated root task if completion occurred, otherwise ``None``.
    Best-effort: swallows exceptions and logs a warning so caller sites
    (e.g. autonomy ticks) remain resilient.
    """
    legacy_workspace_runtime_retired("Workspace root auto-completion")


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


async def _mark_workspace_plan_node_reported(
    *,
    db: AsyncSession,
    workspace_id: str,
    root_goal_task_id: str,
    actor_user_id: str,
    task_metadata: Mapping[str, Any],
    attempt_id: str,
    worker_agent_id: str,
    leader_agent_id: str | None,
) -> None:
    """Do not mirror Core-owned worker reports into retired Workspace Plan SQL."""
    _ = (
        db,
        workspace_id,
        root_goal_task_id,
        actor_user_id,
        task_metadata,
        attempt_id,
        worker_agent_id,
        leader_agent_id,
    )


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
        structured_artifacts, structured_verifications = _worker_report_structured_evidence(payload)
        merged_artifacts.extend(structured_artifacts)
        verifications.extend(structured_verifications)
        verdict = payload.get("verdict") or payload.get("outcome")
        if isinstance(verdict, str) and verdict.strip():
            verifications.append(f"worker_verdict:{verdict.strip()}")
        verification_grade = payload.get("verification_grade")
        if isinstance(verification_grade, str) and verification_grade.strip():
            verifications.append(f"verification_grade:{verification_grade.strip()}")

    if report_type == "completed" and not verifications:
        verifications.append("worker_report:completed")

    merged_artifacts = list(dict.fromkeys(merged_artifacts))
    return normalized_summary, merged_artifacts, list(dict.fromkeys(verifications))


def _worker_report_structured_evidence(payload: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    artifacts: list[str] = []
    verifications: list[str] = []

    payload_artifacts = payload.get("artifacts")
    if isinstance(payload_artifacts, list):
        artifacts.extend(str(item) for item in payload_artifacts if item)

    payload_verifications = payload.get("verifications")
    if isinstance(payload_verifications, list):
        verifications.extend(str(item) for item in payload_verifications if item)

    commit_ref = payload.get("commit_ref")
    if isinstance(commit_ref, str) and commit_ref.strip():
        artifacts.append(f"commit_ref:{commit_ref.strip()}")

    git_diff_summary = payload.get("git_diff_summary")
    if isinstance(git_diff_summary, str) and git_diff_summary.strip():
        artifacts.append(f"git_diff_summary:{git_diff_summary.strip()}")

    changed_files = payload.get("changed_files")
    if isinstance(changed_files, list):
        artifacts.extend(
            f"changed_file:{path}" for path in changed_files if isinstance(path, str) and path
        )

    test_commands = payload.get("test_commands")
    if isinstance(test_commands, list):
        verifications.extend(
            f"test_run:{command}"
            for command in test_commands
            if isinstance(command, str) and command
        )

    return artifacts, verifications


def _is_stale_terminal_worker_report(
    *,
    task_metadata: Mapping[str, Any],
    attempt_id: str,
    report_type: str,
) -> bool:
    """Return True when an old attempt reports after a newer attempt took over."""
    if report_type not in _WORKER_TERMINAL_REPORT_TYPES:
        return False
    current_attempt_id = task_metadata.get(CURRENT_ATTEMPT_ID)
    return (
        isinstance(current_attempt_id, str)
        and bool(current_attempt_id)
        and current_attempt_id != attempt_id
    )


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


def _build_attempt_service(db: AsyncSession) -> WorkspaceTaskSessionAttemptService:
    return WorkspaceTaskSessionAttemptService(
        attempt_repo=legacy_workspace_runtime_retired("Workspace task attempt persistence"),
    )


def _schedule_workspace_retry_attempt(
    *,
    workspace_id: str,
    root_goal_task_id: str,
    workspace_task_id: str,
    attempt_id: str,
    attempt_number: int | str = 1,
    actor_user_id: str,
    leader_agent_id: str,
    retry_feedback: str,
) -> None:
    try:
        retry_attempt_number = int(attempt_number)
    except (TypeError, ValueError):
        retry_attempt_number = 1
    backoff_seconds = DEFAULT_RETRY_POLICY.backoff_for(retry_attempt_number)
    task = asyncio.create_task(
        _launch_workspace_retry_attempt_after_backoff(
            backoff_seconds=backoff_seconds,
            workspace_id=workspace_id,
            root_goal_task_id=root_goal_task_id,
            workspace_task_id=workspace_task_id,
            attempt_id=attempt_id,
            attempt_number=retry_attempt_number,
            actor_user_id=actor_user_id,
            leader_agent_id=leader_agent_id,
            retry_feedback=retry_feedback,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _launch_workspace_retry_attempt_after_backoff(
    *,
    backoff_seconds: float,
    workspace_id: str,
    root_goal_task_id: str,
    workspace_task_id: str,
    attempt_id: str,
    attempt_number: int | str | None = None,
    actor_user_id: str,
    leader_agent_id: str,
    retry_feedback: str,
) -> None:
    if backoff_seconds > 0:
        await asyncio.sleep(backoff_seconds)
    await _launch_workspace_retry_attempt(
        workspace_id=workspace_id,
        root_goal_task_id=root_goal_task_id,
        workspace_task_id=workspace_task_id,
        attempt_id=attempt_id,
        attempt_number=attempt_number,
        actor_user_id=actor_user_id,
        leader_agent_id=leader_agent_id,
        retry_feedback=retry_feedback,
    )


async def _launch_workspace_retry_attempt(
    *,
    workspace_id: str,
    root_goal_task_id: str,
    workspace_task_id: str,
    attempt_id: str,
    attempt_number: int | str | None = None,
    actor_user_id: str,
    leader_agent_id: str,
    retry_feedback: str,
) -> None:
    legacy_workspace_runtime_retired("Workspace retry attempt launch")


async def _ensure_execution_attempt(
    *,
    attempt_service: WorkspaceTaskSessionAttemptService,
    task: WorkspaceTask,
    leader_agent_id: str | None,
) -> WorkspaceTaskSessionAttempt:
    existing_attempt = await attempt_service.get_active_attempt(task.id)
    if existing_attempt is not None:
        return existing_attempt
    attempt = await attempt_service.create_attempt(
        workspace_task_id=task.id,
        root_goal_task_id=str(task.metadata.get(ROOT_GOAL_TASK_ID) or ""),
        workspace_id=task.workspace_id,
        worker_agent_id=task.assignee_agent_id,
        leader_agent_id=persisted_attempt_leader_agent_id(leader_agent_id),
    )
    return await attempt_service.mark_running(attempt.id)


def _worker_report_matches_task_actor(
    *,
    task: WorkspaceTask,
    resolved_attempt: WorkspaceTaskSessionAttempt,
    effective_worker_agent_id: str,
) -> bool:
    if task.assignee_agent_id == effective_worker_agent_id:
        return True

    metadata = task.metadata if isinstance(task.metadata, Mapping) else {}
    attempt_worker_agent_id = getattr(resolved_attempt, "worker_agent_id", None)
    return (
        metadata.get(CURRENT_ATTEMPT_ID) == resolved_attempt.id
        and metadata.get("current_attempt_worker_agent_id") == effective_worker_agent_id
        and attempt_worker_agent_id == effective_worker_agent_id
    )


async def apply_workspace_worker_report(  # noqa: PLR0913
    *,
    workspace_id: str,
    root_goal_task_id: str,
    task_id: str,
    attempt_id: str | None = None,
    conversation_id: str | None = None,
    actor_user_id: str,
    worker_agent_id: str | None,
    report_type: str,
    summary: str,
    artifacts: list[str] | None = None,
    verifications: list[str] | None = None,
    leader_agent_id: str | None = None,
    report_id: str | None = None,
) -> WorkspaceTask | None:
    """Record a worker execution report as candidate output awaiting leader adjudication."""
    legacy_workspace_runtime_retired("Workspace worker report")


async def adjudicate_workspace_worker_report(
    *,
    workspace_id: str,
    task_id: str,
    attempt_id: str | None = None,
    actor_user_id: str,
    status: WorkspaceTaskStatus,
    leader_agent_id: str | None = None,
    title: str | None = None,
    priority: WorkspaceTaskPriority | None = None,
) -> WorkspaceTask | None:
    """Apply a leader decision to a previously ingested worker report."""
    legacy_workspace_runtime_retired("Workspace worker adjudication")


async def resolve_workspace_execution_task_for_delegate(
    *,
    workspace_id: str,
    root_goal_task_id: str,
    delegated_task_text: str,
    subagent_name: str,  # reserved for callers that still pass a delegate label
    workspace_task_id: str | None = None,
) -> WorkspaceTask | None:
    """Resolve a workspace execution task that best matches a delegated subagent task.

    Agent-First iron rule (AGENTS.md): task identity is never inferred from
    text equality on ``title``. Resolution order:

    1. Explicit ``workspace_task_id`` kwarg (caller-provided).
    2. Structured ID extracted from ``delegated_task_text`` via
       :func:`_extract_workspace_task_id` (reads a named ``task_id=...``
       field — structural, analogous to a JSON field read).
    3. Singleton fallback: if the root has exactly one open child, it must
       be the one. (Pure set-membership, allowed.)

    If multiple open children exist and no explicit ID was provided, the
    caller must resolve the ambiguity through an agent tool-call (pick by
    semantic judgment). We return ``None`` instead of guessing.
    """
    legacy_workspace_runtime_retired("Workspace delegation task lookup")


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
    legacy_workspace_runtime_retired("Workspace subagent delegation")


def _extract_workspace_task_id(task_text: str) -> str | None:
    match = _WORKSPACE_TASK_ID_PATTERN.search(task_text)
    if match:
        return match.group(1)
    return None
