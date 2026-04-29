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
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.workspace_agent_autonomy import (
    AUTONOMY_SCHEMA_VERSION,
    GoalCandidateRecordModel,
)
from src.application.services.workspace_agent_autonomy import (
    build_execution_task_harness_metadata,
    is_goal_root_task,
    synthesize_goal_evidence_from_children,
    validate_autonomy_metadata,
)
from src.application.services.workspace_autonomy_profiles import evaluate_completion_evidence
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
from src.application.services.workspace_task_service import (
    WorkspaceTaskAuthorityContext,
    WorkspaceTaskService,
)
from src.application.services.workspace_task_session_attempt_service import (
    WorkspaceTaskSessionAttemptService,
)
from src.domain.events.types import AgentEventType
from src.domain.model.workspace.workspace_task import (
    WorkspaceTask,
    WorkspaceTaskPriority,
    WorkspaceTaskStatus,
)
from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttempt,
    WorkspaceTaskSessionAttemptStatus,
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
from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_session_attempt_repository import (
    SqlWorkspaceTaskSessionAttemptRepository,
)
from src.infrastructure.agent.sisyphus.builtin_agent import BUILTIN_SISYPHUS_ID
from src.infrastructure.agent.state.agent_worker_state import get_redis_client
from src.infrastructure.agent.subagent.task_decomposer import DecompositionResult
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    AUTONOMY_SCHEMA_VERSION_KEY,
    CURRENT_ATTEMPT_ID,
    CURRENT_ATTEMPT_WORKER_BINDING_ID,
    DERIVED_FROM_INTERNAL_PLAN_STEP,
    EXECUTION_STATE,
    LAST_LEADER_ADJUDICATION_STATUS,
    LAST_REPLAN_AT,
    LAST_WORKER_REPORT_SUMMARY,
    LINEAGE_SOURCE,
    PENDING_LEADER_ADJUDICATION,
    REMEDIATION_STATUS,
    REMEDIATION_SUMMARY,
    REPLAN_ATTEMPT_COUNT,
    ROOT_GOAL_TASK_ID,
    TASK_ROLE,
    WORKSPACE_PLAN_ID,
    WORKSPACE_PLAN_NODE_ID,
)

logger = logging.getLogger(__name__)
_background_tasks: set[asyncio.Task[Any]] = set()
_MAX_AUTO_REPLAN_ATTEMPTS = 2
_WORKSPACE_TASK_ID_PATTERN = re.compile(
    r"(?:workspace_task_id|task_id|child_task_id)\s*[:=]\s*([A-Za-z0-9._-]+)",
    re.IGNORECASE,
)
_WORKER_TERMINAL_REPORT_TYPES = frozenset({"completed", "failed", "blocked", "needs_replan"})


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


class TaskDecomposerProtocol(Protocol):
    async def decompose(self, query: str) -> DecompositionResult: ...


# ``workspace_tasks.title`` is ``VARCHAR(255)``. Decomposed step descriptions
# occasionally exceed this when a mention payload or long instruction is used
# verbatim — truncate for the title column but preserve the full text in the
# ``description`` column (``Text``). Keep a small safety margin so ellipsis fits.
_TITLE_MAX_CHARS = 240


def _split_title_description(text: str) -> tuple[str, str | None]:
    """Return a (title, description) pair sized for the DB columns.

    If ``text`` fits in the title column, ``description`` is ``None``. Otherwise
    the title is truncated at the last whitespace boundary within
    ``_TITLE_MAX_CHARS`` (falling back to a hard cut) with an ellipsis, and the
    full original text is placed into ``description`` so no information is lost.
    """
    normalized = (text or "").strip() or "Untitled task"
    if len(normalized) <= _TITLE_MAX_CHARS:
        return normalized, None
    cut = normalized.rfind(" ", 0, _TITLE_MAX_CHARS)
    if cut < int(_TITLE_MAX_CHARS * 0.6):
        cut = _TITLE_MAX_CHARS
    return normalized[:cut].rstrip() + "…", normalized


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
            selected_candidate = _select_existing_root_candidate(candidates, tasks)
            if selected_candidate is None:
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
                candidate=selected_candidate,
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
            if getattr(task, "metadata", {}).get(TASK_ROLE) == "goal_root":
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
            try:
                from src.infrastructure.agent.workspace.worker_launch_drain import (
                    drain_pending_worker_launches_to_outbox,
                )

                _ = await drain_pending_worker_launches_to_outbox(command_service, db)
            except Exception:
                logger.warning(
                    "workspace_goal_runtime.worker_launch_drain_failed",
                    exc_info=True,
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
    remediation_status = getattr(root_task, "metadata", {}).get(REMEDIATION_STATUS)
    root_task_id = getattr(root_task, "id", None)
    if not isinstance(root_task_id, str) or not root_task_id:
        return root_task

    if remediation_status == "replan_required":
        attempts_raw = getattr(root_task, "metadata", {}).get(REPLAN_ATTEMPT_COUNT, 0)
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
        replanned = await _replan_execution_tasks(
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
        if replanned:
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
                actor_agent_id=leader_agent_id,
                reason="workspace_goal_runtime.ready_for_completion.start_root",
                authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
            )
        completed = await command_service.complete_task(
            workspace_id=workspace_id,
            task_id=root_task_id,
            actor_user_id=actor_user_id,
            actor_type="agent",
            actor_agent_id=leader_agent_id,
            reason="workspace_goal_runtime.ready_for_completion",
            authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
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
            return
        # Stale or insufficient evidence: fall through and re-synthesize so
        # accepted child attempts can clear old blocked/failed metadata.

    root_task_id = getattr(root_task, "id", None)
    workspace_id = getattr(root_task, "workspace_id", None)
    if not isinstance(root_task_id, str) or not isinstance(workspace_id, str):
        return

    child_tasks = await task_repo.find_by_root_goal_task_id(workspace_id, root_task_id)
    synthesized = synthesize_goal_evidence_from_children(
        root_task=root_task,
        child_tasks=child_tasks,
        generated_by_agent_id=generated_by_agent_id,
        workspace_metadata=workspace_metadata,
    )
    if synthesized is None:
        return

    metadata["goal_evidence"] = synthesized
    root_task.metadata = validate_autonomy_metadata(metadata)
    _ = await task_repo.save(root_task)


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
    task_repo: SqlWorkspaceTaskRepository,
    workspace_id: object,
) -> dict[str, Any]:
    if not isinstance(workspace_id, str) or not workspace_id:
        return {}
    session = getattr(task_repo, "_session", None)
    if session is None:
        return {}
    try:
        workspace_result = SqlWorkspaceRepository(session).find_by_id(workspace_id)
        workspace = await workspace_result if inspect.isawaitable(workspace_result) else None
    except Exception:
        logger.warning("workspace_goal_runtime.load_workspace_metadata_failed", exc_info=True)
        return {}
    metadata = getattr(workspace, "metadata", None)
    return dict(metadata) if isinstance(metadata, Mapping) else {}


async def _record_root_auto_complete_failure(
    *,
    root_task: WorkspaceTask,
    task_repo: SqlWorkspaceTaskRepository,
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


async def _increment_root_replan_attempt(
    *,
    root_task: WorkspaceTask,
    task_repo: SqlWorkspaceTaskRepository,
    next_attempt_count: int,
) -> None:
    refreshed_root = await task_repo.find_by_id(root_task.id)
    effective_root = refreshed_root or root_task
    metadata = dict(getattr(effective_root, "metadata", {}) or {})
    metadata.setdefault(AUTONOMY_SCHEMA_VERSION_KEY, AUTONOMY_SCHEMA_VERSION)
    metadata[REPLAN_ATTEMPT_COUNT] = next_attempt_count
    metadata[LAST_REPLAN_AT] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
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
        authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
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
    metadata.setdefault(AUTONOMY_SCHEMA_VERSION_KEY, AUTONOMY_SCHEMA_VERSION)
    attempts = metadata.get(REPLAN_ATTEMPT_COUNT, _MAX_AUTO_REPLAN_ATTEMPTS)
    metadata[REMEDIATION_SUMMARY] = (
        f"Auto-replan limit reached after {attempts} attempts; root goal requires human review"
    )
    metadata[LAST_REPLAN_AT] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    effective_root.metadata = validate_autonomy_metadata(metadata)
    updated = await command_service.update_task(
        workspace_id=workspace_id,
        task_id=effective_root.id,
        actor_user_id=actor_user_id,
        metadata=effective_root.metadata,
        actor_type="agent",
        actor_agent_id=leader_agent_id,
        reason="workspace_goal_runtime.human_review_required.metadata",
        authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
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
            authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
        )


async def auto_complete_ready_root(  # noqa: PLR0911 — pre-existing; not touched in this change
    *,
    workspace_id: str,
    actor_user_id: str,
    root_task: WorkspaceTask,
    task_repo: SqlWorkspaceTaskRepository,
    command_service: WorkspaceTaskCommandService,
    leader_agent_id: str | None,
) -> WorkspaceTask | None:
    """Complete the root goal task when all its execution children are DONE.

    Returns the updated root task if completion occurred, otherwise ``None``.
    Best-effort: swallows exceptions and logs a warning so caller sites
    (e.g. autonomy ticks) remain resilient.
    """
    try:
        children = await task_repo.find_by_root_goal_task_id(workspace_id, root_task.id)
    except Exception:
        logger.warning("auto_complete_ready_root: find_by_root_goal_task_id failed", exc_info=True)
        return None
    execution_children = [
        c for c in children if (getattr(c, "metadata", {}) or {}).get(TASK_ROLE) == "execution_task"
    ]
    if not execution_children:
        return None
    if not all(getattr(c.status, "value", c.status) == "done" for c in execution_children):
        return None
    current_status = getattr(root_task.status, "value", root_task.status)
    if current_status == "done":
        return None

    # The root goal policy requires metadata.goal_evidence before completion.
    # Synthesize it from the done children so the completion guardrail accepts
    # the transition. Mirrors _handle_remediation_complete_root_goal.
    try:
        await _ensure_root_goal_evidence(
            root_task=root_task,
            task_repo=task_repo,
            generated_by_agent_id=leader_agent_id or str(actor_user_id),
        )
    except Exception as exc:
        logger.warning("auto_complete_ready_root: ensure_goal_evidence failed", exc_info=True)
        await _record_root_auto_complete_failure(
            root_task=root_task,
            task_repo=task_repo,
            reason=f"root auto-complete evidence synthesis failed: {exc}",
        )
        return None

    refreshed = await task_repo.find_by_id(root_task.id)
    if refreshed is None:
        return None
    if getattr(refreshed.status, "value", refreshed.status) == "done":
        return None

    try:
        if getattr(refreshed.status, "value", refreshed.status) == "todo":
            refreshed = await command_service.start_task(
                workspace_id=workspace_id,
                task_id=refreshed.id,
                actor_user_id=actor_user_id,
                actor_type="agent",
                actor_agent_id=leader_agent_id,
                reason="workspace_goal_runtime.auto_complete_ready_root.start_root",
                authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
            )
        return await command_service.complete_task(
            workspace_id=workspace_id,
            task_id=refreshed.id,
            actor_user_id=actor_user_id,
            actor_type="agent",
            actor_agent_id=leader_agent_id,
            reason="workspace_goal_runtime.auto_complete_ready_root",
            authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
        )
    except Exception as exc:
        logger.warning("auto_complete_ready_root: complete_task failed", exc_info=True)
        await _record_root_auto_complete_failure(
            root_task=refreshed,
            task_repo=task_repo,
            reason=f"root auto-complete failed: {exc}",
        )
        return None


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

    remediation_status = getattr(root_task, "metadata", {}).get(REMEDIATION_STATUS)
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
        step_title, step_description = _split_title_description(description)
        feature_id = step_id or f"bootstrap-{index}"
        created_tasks.append(
            await command_service.create_task(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                title=step_title,
                description=step_description,
                metadata={
                    AUTONOMY_SCHEMA_VERSION_KEY: 1,
                    TASK_ROLE: "execution_task",
                    ROOT_GOAL_TASK_ID: root_task_id,
                    LINEAGE_SOURCE: "agent",
                    DERIVED_FROM_INTERNAL_PLAN_STEP: feature_id,
                    **build_execution_task_harness_metadata(
                        feature_id=feature_id,
                        sequence=index,
                        title=step_title,
                        description=step_description or description,
                    ),
                    EXECUTION_STATE: _build_execution_state(
                        phase="todo",
                        reason="workspace_goal_runtime.bootstrap_execution_tasks",
                        action="created",
                        actor_id=leader_agent_id or actor_user_id,
                    ),
                },
                actor_type="agent",
                reason="workspace_goal_runtime.bootstrap_execution_tasks",
                authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
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


def _is_workspace_plan_linked_task(task: WorkspaceTask) -> bool:
    metadata = getattr(task, "metadata", None)
    if not isinstance(metadata, Mapping):
        return False
    plan_id = metadata.get(WORKSPACE_PLAN_ID)
    node_id = metadata.get(WORKSPACE_PLAN_NODE_ID)
    return isinstance(plan_id, str) and bool(plan_id) and isinstance(node_id, str) and bool(node_id)


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
) -> bool:
    root_task_id = getattr(root_task, "id", None)
    root_title = getattr(root_task, "title", "")
    if not isinstance(root_task_id, str) or not root_task_id:
        return False

    existing_children = await task_repo.find_by_root_goal_task_id(workspace_id, root_task_id)
    plan_linked_children = [
        child for child in existing_children if _is_workspace_plan_linked_task(child)
    ]
    children_to_replace = [
        child for child in existing_children if not _is_workspace_plan_linked_task(child)
    ]
    if plan_linked_children:
        for child in children_to_replace:
            _ = await command_service.delete_task(
                workspace_id=workspace_id,
                task_id=child.id,
                actor_user_id=actor_user_id,
                authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
            )
        logger.info(
            "workspace_goal_runtime.replan_skipped_for_durable_plan",
            extra={
                "event": "workspace_goal_runtime.replan_skipped_for_durable_plan",
                "workspace_id": workspace_id,
                "root_task_id": root_task_id,
                "plan_linked_child_count": len(plan_linked_children),
                "non_plan_child_deleted_count": len(children_to_replace),
            },
        )
        return False

    for child in children_to_replace:
        _ = await command_service.delete_task(
            workspace_id=workspace_id,
            task_id=child.id,
            actor_user_id=actor_user_id,
            authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
        )

    decomposed_steps = await _decompose_root_goal(
        task_decomposer=task_decomposer,
        root_title=root_title or user_query,
        user_query=user_query,
    )
    created_tasks: list[WorkspaceTask] = []
    for index, (step_id, description) in enumerate(decomposed_steps, start=1):
        step_title, step_description = _split_title_description(description)
        feature_id = step_id or f"replan-{index}"
        created_tasks.append(
            await command_service.create_task(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                title=step_title,
                description=step_description,
                metadata={
                    AUTONOMY_SCHEMA_VERSION_KEY: 1,
                    TASK_ROLE: "execution_task",
                    ROOT_GOAL_TASK_ID: root_task_id,
                    LINEAGE_SOURCE: "agent",
                    DERIVED_FROM_INTERNAL_PLAN_STEP: feature_id,
                    **build_execution_task_harness_metadata(
                        feature_id=feature_id,
                        sequence=index,
                        title=step_title,
                        description=step_description or description,
                    ),
                    EXECUTION_STATE: _build_execution_state(
                        phase="todo",
                        reason="workspace_goal_runtime.replan_execution_tasks",
                        action="created",
                        actor_id=leader_agent_id or actor_user_id,
                    ),
                },
                actor_type="agent",
                reason="workspace_goal_runtime.replan_execution_tasks",
                authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
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
    return True


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
    """Mirror terminal workspace worker reports into the durable V2 plan state."""
    plan_id = task_metadata.get(WORKSPACE_PLAN_ID)
    node_id = task_metadata.get(WORKSPACE_PLAN_NODE_ID)
    if not isinstance(plan_id, str) or not plan_id:
        return
    if not isinstance(node_id, str) or not node_id:
        return

    try:
        from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_events import (
            SqlWorkspacePlanEventRepository,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_outbox import (
            SqlWorkspacePlanOutboxRepository,
        )
        from src.infrastructure.agent.workspace_plan import build_sql_orchestrator
        from src.infrastructure.agent.workspace_plan.outbox_handlers import (
            SUPERVISOR_TICK_EVENT,
        )

        await SqlWorkspacePlanEventRepository(db).append(
            plan_id=plan_id,
            workspace_id=workspace_id,
            node_id=node_id,
            attempt_id=attempt_id,
            actor_id=worker_agent_id,
            event_type="worker_report_terminal",
            source="worker_report",
            payload={
                "report_type": task_metadata.get("last_worker_report_type"),
                "summary": task_metadata.get(LAST_WORKER_REPORT_SUMMARY),
                "artifacts": task_metadata.get("last_worker_report_artifacts", []),
                "verifications": task_metadata.get("last_worker_report_verifications", []),
                "reported_at": task_metadata.get("last_worker_reported_at"),
            },
        )
        orchestrator = build_sql_orchestrator(db)
        await orchestrator.mark_worker_reported(
            workspace_id=workspace_id,
            node_id=node_id,
            attempt_id=attempt_id,
        )
        _ = await SqlWorkspacePlanOutboxRepository(db).enqueue(
            plan_id=plan_id,
            workspace_id=workspace_id,
            event_type=SUPERVISOR_TICK_EVENT,
            payload={
                "workspace_id": workspace_id,
                "root_task_id": root_goal_task_id,
                "actor_user_id": actor_user_id,
                "leader_agent_id": leader_agent_id,
            },
            metadata={
                "source": "worker_report",
                "node_id": node_id,
                "attempt_id": attempt_id,
            },
        )
    except Exception:
        logger.warning(
            "workspace_v2.worker_report_sync_failed",
            extra={
                "event": "workspace_v2.worker_report_sync_failed",
                "workspace_id": workspace_id,
                "plan_id": plan_id,
                "node_id": node_id,
            },
            exc_info=True,
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
        attempt_repo=SqlWorkspaceTaskSessionAttemptRepository(db),
    )


def _schedule_workspace_retry_attempt(
    *,
    workspace_id: str,
    root_goal_task_id: str,
    workspace_task_id: str,
    attempt_id: str,
    actor_user_id: str,
    leader_agent_id: str,
    retry_feedback: str,
) -> None:
    task = asyncio.create_task(
        _launch_workspace_retry_attempt(
            workspace_id=workspace_id,
            root_goal_task_id=root_goal_task_id,
            workspace_task_id=workspace_task_id,
            attempt_id=attempt_id,
            actor_user_id=actor_user_id,
            leader_agent_id=leader_agent_id,
            retry_feedback=retry_feedback,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _launch_workspace_retry_attempt(
    *,
    workspace_id: str,
    root_goal_task_id: str,
    workspace_task_id: str,
    attempt_id: str,
    actor_user_id: str,
    leader_agent_id: str,
    retry_feedback: str,
) -> None:
    from src.application.services.agent_service import AgentService
    from src.application.services.workspace_mention_router import WorkspaceMentionRouter
    from src.configuration.di_container import DIContainer
    from src.configuration.factories import create_llm_client
    from src.domain.model.agent import Conversation, ConversationStatus

    conversation_scope = f"task:{workspace_task_id}:attempt:{attempt_id}"
    conversation_id = WorkspaceMentionRouter.workspace_conversation_id(
        workspace_id,
        leader_agent_id,
        conversation_scope=conversation_scope,
    )
    worker_binding_id: str | None = None
    try:
        async with async_session_factory() as db:
            task = await SqlWorkspaceTaskRepository(db).find_by_id(workspace_task_id)
            if task is not None:
                worker_binding_id = task.get_workspace_agent_binding_id()
                if worker_binding_id is None and task.assignee_agent_id:
                    binding = await SqlWorkspaceAgentRepository(db).find_by_workspace_and_agent_id(
                        workspace_id=workspace_id,
                        agent_id=task.assignee_agent_id,
                    )
                    worker_binding_id = binding.id if binding is not None else None
    except Exception:
        logger.warning(
            "Workspace retry launch could not resolve worker binding id",
            exc_info=True,
            extra={"workspace_id": workspace_id, "workspace_task_id": workspace_task_id},
        )
    worker_binding_line = (
        f"workspace_agent_binding_id={worker_binding_id}\n" if worker_binding_id else ""
    )
    user_message = (
        "Please continue autonomous workspace task execution for the existing workspace task. "
        "Review the previous attempt feedback, relaunch execution for the same task, and keep "
        "the same workspace task identity. Do not structurally replan the root goal unless the "
        "task is impossible under the current scope.\n\n"
        "[workspace-task-binding]\n"
        f"workspace_task_id={workspace_task_id}\n"
        f"attempt_id={attempt_id}\n"
        f"root_goal_task_id={root_goal_task_id}\n"
        f"workspace_id={workspace_id}\n"
        f"{worker_binding_line}"
        "[/workspace-task-binding]\n\n"
        f"Leader retry feedback: {retry_feedback.strip() or 'rework required'}"
    )

    try:
        redis_client = await get_redis_client()
        async with async_session_factory() as db:
            workspace_repo = SqlWorkspaceRepository(db)
            workspace = await workspace_repo.find_by_id(workspace_id)
            if workspace is None:
                logger.warning(
                    "Workspace retry launch skipped because workspace %s was not found",
                    workspace_id,
                )
                return
            conversation_repo = DIContainer(
                db=db, redis_client=redis_client
            ).conversation_repository()
            conversation = await conversation_repo.find_by_id(conversation_id)
            if conversation is None:
                conversation = Conversation(
                    id=conversation_id,
                    project_id=workspace.project_id,
                    tenant_id=workspace.tenant_id,
                    user_id=actor_user_id,
                    title=f"Workspace Retry - {workspace_task_id}",
                    status=ConversationStatus.ACTIVE,
                    agent_config={"selected_agent_id": leader_agent_id},
                    metadata={
                        "workspace_id": workspace_id,
                        "agent_id": leader_agent_id,
                        "workspace_agent_binding_id": worker_binding_id,
                        "workspace_task_id": workspace_task_id,
                        ROOT_GOAL_TASK_ID: root_goal_task_id,
                        "attempt_id": attempt_id,
                        "conversation_scope": conversation_scope,
                        "retry_launch": True,
                        "created_at": datetime.now(UTC).isoformat(),
                    },
                    message_count=0,
                    created_at=datetime.now(UTC),
                )
                await conversation_repo.save(conversation)
                await db.commit()

            llm = await create_llm_client(workspace.tenant_id)
            container = DIContainer(db=db, redis_client=redis_client)
            agent_service: AgentService = container.agent_service(llm)
            async for _ in agent_service.stream_chat_v2(
                conversation_id=conversation_id,
                user_message=user_message,
                project_id=workspace.project_id,
                user_id=actor_user_id,
                tenant_id=workspace.tenant_id,
                agent_id=leader_agent_id,
            ):
                pass
    except Exception:
        logger.warning(
            "Workspace retry attempt launch failed",
            extra={
                "workspace_id": workspace_id,
                "workspace_task_id": workspace_task_id,
                "attempt_id": attempt_id,
                "leader_agent_id": leader_agent_id,
            },
            exc_info=True,
        )


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
        leader_agent_id=leader_agent_id,
    )
    return await attempt_service.mark_running(attempt.id)


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
        logger.warning(
            "_assign_execution_tasks_to_workers: no active workspace agents",
            extra={
                "event": "workspace_assign.no_active_members",
                "workspace_id": workspace_id,
                "leader_agent_id": leader_agent_id,
                "created_count": len(created_tasks),
                "reason": reason,
            },
        )
        return

    effective_leader_agent_id = leader_agent_id
    if any(binding.agent_id == BUILTIN_SISYPHUS_ID for binding in active_bindings):
        if leader_agent_id != BUILTIN_SISYPHUS_ID:
            logger.warning(
                "_assign_execution_tasks_to_workers: corrected leader identity to builtin",
                extra={
                    "event": "workspace_assign.corrected_leader_agent_id",
                    "workspace_id": workspace_id,
                    "requested_leader_agent_id": leader_agent_id,
                    "effective_leader_agent_id": BUILTIN_SISYPHUS_ID,
                    "created_count": len(created_tasks),
                    "reason": reason,
                },
            )
        effective_leader_agent_id = BUILTIN_SISYPHUS_ID

    worker_bindings = [
        binding for binding in active_bindings if binding.agent_id != effective_leader_agent_id
    ]
    if not worker_bindings:
        # Do NOT fall back to assigning the leader as worker — that violates
        # the leader/worker separation and causes workers to run with
        # task_authority=leader (which in turn skips worker-specific
        # guardrails). Leave tasks unassigned; the UI / autonomy tick will
        # surface this state so the user can add a worker agent.
        logger.warning(
            "_assign_execution_tasks_to_workers: no non-leader workspace members",
            extra={
                "event": "workspace_assign.no_worker_members",
                "workspace_id": workspace_id,
                "leader_agent_id": effective_leader_agent_id,
                "created_count": len(created_tasks),
                "active_binding_count": len(active_bindings),
                "reason": reason,
            },
        )
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
            actor_agent_id=effective_leader_agent_id,
            reason=reason,
            authority=WorkspaceTaskAuthorityContext.leader(effective_leader_agent_id),
        )


async def apply_workspace_worker_report(  # noqa: C901, PLR0912, PLR0913, PLR0915
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
    artifacts = [artifact for artifact in (artifacts or []) if artifact]
    explicit_verifications = [
        verification
        for verification in (verifications or [])
        if isinstance(verification, str) and verification
    ]
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
            attempt_service = _build_attempt_service(db)

            task = await task_service.get_task(
                workspace_id=workspace_id,
                task_id=task_id,
                actor_user_id=actor_user_id,
            )
            if task.metadata.get(ROOT_GOAL_TASK_ID) != root_goal_task_id:
                raise ValueError("Worker report task does not belong to the provided root goal")
            resolved_attempt: WorkspaceTaskSessionAttempt
            if attempt_id:
                attempt = await attempt_service.get_attempt(attempt_id)
                if attempt is None or attempt.workspace_task_id != task.id:
                    raise ValueError("Worker report attempt_id does not match the task")
                resolved_attempt = attempt
            else:
                resolved_attempt = await _ensure_execution_attempt(
                    attempt_service=attempt_service,
                    task=task,
                    leader_agent_id=leader_agent_id,
                )
            effective_worker_agent_id = worker_agent_id or resolved_attempt.worker_agent_id
            if not isinstance(effective_worker_agent_id, str) or not effective_worker_agent_id:
                raise ValueError("Worker report requires an attempt-bound worker_agent_id")
            if task.assignee_agent_id != effective_worker_agent_id:
                raise ValueError("Worker report does not match the task assignee")

            metadata = dict(task.metadata)
            v2_plan_linked = (
                isinstance(metadata.get(WORKSPACE_PLAN_ID), str)
                and bool(metadata.get(WORKSPACE_PLAN_ID))
                and isinstance(metadata.get(WORKSPACE_PLAN_NODE_ID), str)
                and bool(metadata.get(WORKSPACE_PLAN_NODE_ID))
            )
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
            report_verifications = list(
                dict.fromkeys([*explicit_verifications, *report_verifications])
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
            metadata["last_worker_report_type"] = report_type
            metadata[LAST_WORKER_REPORT_SUMMARY] = normalized_summary
            metadata["last_worker_report_artifacts"] = list(merged_artifacts)
            metadata["last_worker_report_verifications"] = list(dict.fromkeys(report_verifications))
            metadata["last_worker_reported_at"] = reported_at
            metadata["last_worker_report_fingerprint"] = report_fingerprint
            metadata[PENDING_LEADER_ADJUDICATION] = (
                report_type in _WORKER_TERMINAL_REPORT_TYPES and not v2_plan_linked
            )
            if report_id:
                metadata["last_worker_report_id"] = report_id
            metadata[CURRENT_ATTEMPT_ID] = resolved_attempt.id
            metadata["last_attempt_id"] = resolved_attempt.id
            metadata["current_attempt_number"] = resolved_attempt.attempt_number
            phase = "in_progress"
            if report_type in _WORKER_TERMINAL_REPORT_TYPES:
                action = (
                    "await_plan_verification" if v2_plan_linked else "await_leader_adjudication"
                )
            else:
                action = "start"
            metadata["last_attempt_status"] = (
                "awaiting_plan_verification"
                if report_type in _WORKER_TERMINAL_REPORT_TYPES and v2_plan_linked
                else WorkspaceTaskSessionAttemptStatus.AWAITING_LEADER_ADJUDICATION.value
                if report_type in _WORKER_TERMINAL_REPORT_TYPES
                else WorkspaceTaskSessionAttemptStatus.RUNNING.value
            )
            metadata[EXECUTION_STATE] = _build_execution_state(
                phase=phase,
                reason=f"workspace_goal_runtime.worker_report.{report_type}:{normalized_summary}",
                action=action,
                actor_id=effective_worker_agent_id,
            )

            worker_authority = WorkspaceTaskAuthorityContext.worker(effective_worker_agent_id)
            worker_metadata_patch = {
                key: metadata[key]
                for key in (
                    EXECUTION_STATE,
                    "evidence_refs",
                    "execution_verifications",
                    "last_worker_report_type",
                    LAST_WORKER_REPORT_SUMMARY,
                    "last_worker_report_artifacts",
                    "last_worker_report_verifications",
                    "last_worker_reported_at",
                    "last_worker_report_fingerprint",
                    "last_worker_report_id",
                    PENDING_LEADER_ADJUDICATION,
                    CURRENT_ATTEMPT_ID,
                    "last_attempt_id",
                    "current_attempt_number",
                    "last_attempt_status",
                )
                if key in metadata
            }
            updated = await command_service.update_task(
                workspace_id=workspace_id,
                task_id=task_id,
                actor_user_id=actor_user_id,
                metadata=worker_metadata_patch,
                blocker_reason=(
                    normalized_summary
                    if report_type in {"blocked", "failed", "needs_replan"}
                    else None
                ),
                actor_type="agent",
                actor_agent_id=effective_worker_agent_id,
                reason=f"workspace_goal_runtime.worker_report.{report_type}.metadata",
                authority=worker_authority,
            )
            if updated.status.value == "todo":
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
                    reason=f"workspace_goal_runtime.worker_report.{report_type}.start_root",
                )
                updated = await command_service.start_task(
                    workspace_id=workspace_id,
                    task_id=task_id,
                    actor_user_id=actor_user_id,
                    actor_type="agent",
                    actor_agent_id=effective_worker_agent_id,
                    reason=f"workspace_goal_runtime.worker_report.{report_type}.start",
                    authority=worker_authority,
                )

            if report_type in _WORKER_TERMINAL_REPORT_TYPES:
                await attempt_service.record_candidate_output(
                    resolved_attempt.id,
                    summary=normalized_summary,
                    artifacts=merged_artifacts,
                    verifications=list(
                        dict.fromkeys([*prior_verifications, *report_verifications])
                    ),
                    conversation_id=conversation_id,
                )
                await _mark_workspace_plan_node_reported(
                    db=db,
                    workspace_id=workspace_id,
                    root_goal_task_id=root_goal_task_id,
                    actor_user_id=actor_user_id,
                    task_metadata=metadata,
                    attempt_id=resolved_attempt.id,
                    worker_agent_id=effective_worker_agent_id,
                    leader_agent_id=leader_agent_id,
                )
            elif resolved_attempt.status == WorkspaceTaskSessionAttemptStatus.PENDING:
                await attempt_service.mark_running(resolved_attempt.id)

            await db.commit()
            try:
                publisher = WorkspaceTaskEventPublisher(await get_redis_client())
                await publisher.publish_pending_events(command_service.consume_pending_events())
            except Exception:
                logger.warning(
                    "Workspace worker report event publish failed after commit",
                    exc_info=True,
                    extra={
                        "workspace_id": workspace_id,
                        "task_id": task_id,
                        "attempt_id": resolved_attempt.id,
                    },
                )
            if report_type in _WORKER_TERMINAL_REPORT_TYPES:
                try:
                    from src.infrastructure.adapters.primary.web.routers.workspace_leader_bootstrap import (
                        schedule_autonomy_tick,
                    )

                    schedule_autonomy_tick(workspace_id, actor_user_id)
                except Exception:
                    logger.warning("schedule_autonomy_tick failed", exc_info=True)
            return updated
    except Exception:
        logger.warning("Workspace worker report application failed", exc_info=True)
        return None


async def adjudicate_workspace_worker_report(  # noqa: C901, PLR0912, PLR0915
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
            attempt_service = _build_attempt_service(db)

            task = await task_service.get_task(
                workspace_id=workspace_id,
                task_id=task_id,
                actor_user_id=actor_user_id,
            )
            metadata = dict(task.metadata)
            current_attempt_id = attempt_id
            if current_attempt_id is None:
                maybe_attempt = metadata.get(CURRENT_ATTEMPT_ID)
                current_attempt_id = (
                    maybe_attempt if isinstance(maybe_attempt, str) and maybe_attempt else None
                )
            summary = str(metadata.get(LAST_WORKER_REPORT_SUMMARY) or "").strip()
            if metadata.get(PENDING_LEADER_ADJUDICATION) is True:
                metadata[PENDING_LEADER_ADJUDICATION] = False
            metadata[LAST_LEADER_ADJUDICATION_STATUS] = status.value
            metadata["last_leader_adjudicated_at"] = (
                datetime.now(UTC)
                .isoformat()
                .replace(
                    "+00:00",
                    "Z",
                )
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
            metadata[EXECUTION_STATE] = _build_execution_state(
                phase=phase_map[status],
                reason=f"workspace_goal_runtime.leader_adjudication.{status.value}:{summary or task.title}",
                action=action_map[status],
                actor_id=leader_agent_id or actor_user_id,
            )

            retry_launch_request: dict[str, str] | None = None
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
                authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
            )
            if current_attempt_id:
                if status == WorkspaceTaskStatus.DONE:
                    accepted_attempt = await attempt_service.accept(
                        current_attempt_id,
                        leader_feedback=summary or None,
                    )
                    metadata["last_worker_report_type"] = "completed"
                    metadata["last_attempt_status"] = accepted_attempt.status.value
                    metadata["last_attempt_id"] = accepted_attempt.id
                    metadata[CURRENT_ATTEMPT_ID] = accepted_attempt.id
                elif status == WorkspaceTaskStatus.BLOCKED:
                    blocked_attempt = await attempt_service.block(
                        current_attempt_id,
                        leader_feedback=summary or task.title,
                        adjudication_reason="leader_blocked",
                    )
                    metadata["last_attempt_status"] = blocked_attempt.status.value
                    metadata["last_attempt_id"] = blocked_attempt.id
                    metadata[CURRENT_ATTEMPT_ID] = blocked_attempt.id
                elif status == WorkspaceTaskStatus.IN_PROGRESS:
                    rejected_attempt = await attempt_service.reject(
                        current_attempt_id,
                        leader_feedback=summary or task.title,
                        adjudication_reason="leader_rework_required",
                    )
                    new_attempt = await attempt_service.create_attempt(
                        workspace_task_id=task.id,
                        root_goal_task_id=str(task.metadata.get(ROOT_GOAL_TASK_ID) or ""),
                        workspace_id=workspace_id,
                        worker_agent_id=task.assignee_agent_id,
                        leader_agent_id=leader_agent_id,
                    )
                    metadata["last_attempt_status"] = rejected_attempt.status.value
                    metadata["last_attempt_id"] = rejected_attempt.id
                    metadata[CURRENT_ATTEMPT_ID] = new_attempt.id
                    metadata["current_attempt_number"] = new_attempt.attempt_number
                    worker_binding_id = task.get_workspace_agent_binding_id()
                    if worker_binding_id is None and task.assignee_agent_id:
                        binding = await SqlWorkspaceAgentRepository(
                            db
                        ).find_by_workspace_and_agent_id(
                            workspace_id=workspace_id,
                            agent_id=task.assignee_agent_id,
                        )
                        worker_binding_id = binding.id if binding is not None else None
                    if worker_binding_id:
                        metadata[CURRENT_ATTEMPT_WORKER_BINDING_ID] = worker_binding_id
                    if leader_agent_id and task.assignee_agent_id:
                        retry_launch_request = {
                            "workspace_id": workspace_id,
                            ROOT_GOAL_TASK_ID: str(task.metadata.get(ROOT_GOAL_TASK_ID) or ""),
                            "workspace_task_id": task.id,
                            "attempt_id": new_attempt.id,
                            "actor_user_id": actor_user_id,
                            "leader_agent_id": leader_agent_id,
                            "retry_feedback": summary or task.title,
                        }
                updated = await command_service.update_task(
                    workspace_id=workspace_id,
                    task_id=task_id,
                    actor_user_id=actor_user_id,
                    metadata=metadata,
                    actor_type="agent",
                    actor_agent_id=leader_agent_id,
                    reason=f"workspace_goal_runtime.leader_adjudication.{status.value}.attempt_metadata",
                    authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
                )
            if status == WorkspaceTaskStatus.IN_PROGRESS and updated.status.value == "todo":
                root_goal_task_id = task.metadata.get(ROOT_GOAL_TASK_ID)
                if isinstance(root_goal_task_id, str) and root_goal_task_id:
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
                        reason="workspace_goal_runtime.leader_adjudication.in_progress.start_root",
                    )
                updated = await command_service.start_task(
                    workspace_id=workspace_id,
                    task_id=task_id,
                    actor_user_id=actor_user_id,
                    actor_type="agent",
                    actor_agent_id=leader_agent_id,
                    reason="workspace_goal_runtime.leader_adjudication.in_progress.start",
                    authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
                )
            elif status == WorkspaceTaskStatus.DONE and updated.status.value != "done":
                updated = await command_service.complete_task(
                    workspace_id=workspace_id,
                    task_id=task_id,
                    actor_user_id=actor_user_id,
                    actor_type="agent",
                    actor_agent_id=leader_agent_id,
                    reason="workspace_goal_runtime.leader_adjudication.completed.complete",
                    authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
                )
            elif status == WorkspaceTaskStatus.BLOCKED and updated.status.value not in (
                "blocked",
                "done",
            ):
                updated = await command_service.block_task(
                    workspace_id=workspace_id,
                    task_id=task_id,
                    actor_user_id=actor_user_id,
                    actor_type="agent",
                    actor_agent_id=leader_agent_id,
                    reason="workspace_goal_runtime.leader_adjudication.blocked.block",
                    authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
                )

            await db.commit()
            publisher = WorkspaceTaskEventPublisher(await get_redis_client())
            await publisher.publish_pending_events(command_service.consume_pending_events())
            if retry_launch_request is not None:
                _schedule_workspace_retry_attempt(**retry_launch_request)
            return updated
    except Exception:
        logger.warning("Workspace worker report adjudication failed", exc_info=True)
        return None


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
                    and task.metadata.get(ROOT_GOAL_TASK_ID) == root_goal_task_id
                ):
                    return task

            candidates = await task_repo.find_by_root_goal_task_id(workspace_id, root_goal_task_id)
            open_candidates = [
                task for task in candidates if task.status != WorkspaceTaskStatus.DONE
            ]
            if not open_candidates:
                return None

            # Agent-First: singleton fallback is pure set-membership (exactly one open task).
            # Ambiguous multi-candidate cases require an explicit ID from the caller.
            if len(open_candidates) == 1:
                return open_candidates[0]

            logger.info(
                "Workspace delegate resolution ambiguous: %d open candidates, "
                "no explicit workspace_task_id provided (caller must supply one).",
                len(open_candidates),
            )
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
            attempt_service = _build_attempt_service(db)
            attempt = await _ensure_execution_attempt(
                attempt_service=attempt_service,
                task=task,
                leader_agent_id=leader_agent_id,
            )

            metadata = dict(task.metadata)
            metadata["delegated_subagent_name"] = subagent_name
            if subagent_id:
                metadata["delegated_subagent_id"] = subagent_id
            metadata["delegated_task_text"] = delegated_task_text.strip()
            metadata[CURRENT_ATTEMPT_ID] = attempt.id
            metadata["last_attempt_id"] = attempt.id
            metadata["current_attempt_number"] = attempt.attempt_number
            metadata["last_attempt_status"] = attempt.status.value
            if attempt.worker_agent_id:
                metadata["current_attempt_worker_agent_id"] = attempt.worker_agent_id
            worker_binding_id = task.get_workspace_agent_binding_id()
            if worker_binding_id:
                metadata[CURRENT_ATTEMPT_WORKER_BINDING_ID] = worker_binding_id

            updated = await command_service.update_task(
                workspace_id=workspace_id,
                task_id=task.id,
                actor_user_id=actor_user_id,
                metadata=metadata,
                actor_type="agent",
                actor_agent_id=leader_agent_id,
                reason="workspace_goal_runtime.prepare_subagent_delegation.metadata",
                authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
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
            if updated.status == WorkspaceTaskStatus.TODO:
                updated = await command_service.start_task(
                    workspace_id=workspace_id,
                    task_id=task.id,
                    actor_user_id=actor_user_id,
                    actor_type="agent",
                    actor_agent_id=leader_agent_id,
                    reason="workspace_goal_runtime.prepare_subagent_delegation.start",
                    authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
                )

            await db.commit()
            publisher = WorkspaceTaskEventPublisher(await get_redis_client())
            await publisher.publish_pending_events(command_service.consume_pending_events())
            return {
                "workspace_task_id": updated.id,
                "attempt_id": attempt.id,
                "worker_agent_id": attempt.worker_agent_id or "",
                "workspace_agent_binding_id": updated.get_workspace_agent_binding_id() or "",
                "workspace_id": workspace_id,
                ROOT_GOAL_TASK_ID: root_goal_task_id,
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
