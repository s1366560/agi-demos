"""Handlers for durable workspace plan outbox jobs."""

from __future__ import annotations

import contextlib
import json
import logging
import shlex
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.workspace_agent_autonomy import AUTONOMY_SCHEMA_VERSION
from src.application.services.workspace_task_command_service import WorkspaceTaskCommandService
from src.application.services.workspace_task_service import (
    WorkspaceTaskAuthorityContext,
    WorkspaceTaskService,
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
from src.domain.model.workspace_plan import (
    HandoffPackage,
    HandoffReason,
    PlanNode,
    PlanNodeId,
    TaskExecution,
    TaskIntent,
)
from src.domain.ports.services.task_allocator_port import (
    Allocation,
    WorkspaceAgent as AllocatorAgent,
)
from src.domain.ports.services.verifier_port import VerificationContext
from src.infrastructure.adapters.secondary.persistence.models import (
    WorkspacePlanOutboxModel,
    WorkspaceTaskModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_plan_repository import SqlPlanRepository
from src.infrastructure.adapters.secondary.persistence.sql_workspace_agent_repository import (
    SqlWorkspaceAgentRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_member_repository import (
    SqlWorkspaceMemberRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_outbox import (
    SqlWorkspacePlanOutboxRepository,
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
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    AUTONOMY_SCHEMA_VERSION_KEY,
    CURRENT_ATTEMPT_ID,
    CURRENT_ATTEMPT_WORKER_BINDING_ID,
    DERIVED_FROM_INTERNAL_PLAN_STEP,
    EXECUTION_STATE,
    LAST_WORKER_REPORT_SUMMARY,
    LINEAGE_SOURCE,
    ROOT_GOAL_TASK_ID,
    TASK_ROLE,
    WORKSPACE_AGENT_BINDING_ID,
    WORKSPACE_PLAN_ID,
    WORKSPACE_PLAN_NODE_ID,
)
from src.infrastructure.agent.workspace_plan.factory import build_sql_orchestrator
from src.infrastructure.agent.workspace_plan.orchestrator import OrchestratorConfig
from src.infrastructure.agent.workspace_plan.outbox_worker import WorkspacePlanOutboxHandler
from src.infrastructure.agent.workspace_plan.supervisor import (
    AgentPoolProvider,
    AttemptContextProvider,
    Dispatcher,
    ProgressSink,
)

SUPERVISOR_TICK_EVENT = "supervisor_tick"
WORKER_LAUNCH_EVENT = "worker_launch"
HANDOFF_RESUME_EVENT = "handoff_resume"
ATTEMPT_RETRY_EVENT = "attempt_retry"
logger = logging.getLogger(__name__)

WorktreePreparer = Callable[[AsyncSession, str, WorkspaceTask, str | None], Awaitable[str | None]]


def _build_dispatch_execution_state(*, actor_id: str) -> dict[str, str]:
    return {
        "phase": "in_progress",
        "last_agent_reason": "workspace_plan.dispatch.project_attempt",
        "last_agent_action": "start",
        "updated_by_actor_type": "agent",
        "updated_by_actor_id": actor_id,
        "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }


def make_supervisor_tick_handler(
    *,
    config: OrchestratorConfig | None = None,
    agent_pool: AgentPoolProvider | None = None,
    dispatcher: Dispatcher | None = None,
    attempt_context: AttemptContextProvider | None = None,
    progress_sink: ProgressSink | None = None,
) -> WorkspacePlanOutboxHandler:
    """Build an outbox handler that runs one SQL-backed supervisor tick."""

    async def _handle(item: WorkspacePlanOutboxModel, session: AsyncSession) -> None:
        workspace_id = str(item.payload_json.get("workspace_id") or item.workspace_id)
        payload = dict(item.payload_json or {})
        orchestrator = build_sql_orchestrator(
            session,
            config=config,
            agent_pool=agent_pool or _make_sql_agent_pool(session),
            dispatcher=dispatcher or _make_sql_dispatcher(session, item, payload),
            attempt_context=attempt_context or _make_sql_attempt_context(session),
            progress_sink=progress_sink,
        )
        report = await orchestrator.tick_once(workspace_id)
        if report.errors:
            raise RuntimeError("; ".join(report.errors))

    return _handle


def _make_sql_agent_pool(session: AsyncSession) -> AgentPoolProvider:
    async def _agent_pool(workspace_id: str) -> list[AllocatorAgent]:
        binding_repo = SqlWorkspaceAgentRepository(session)
        task_repo = SqlWorkspaceTaskRepository(session)
        bindings = await binding_repo.find_by_workspace(workspace_id, active_only=True, limit=500)
        tasks = await task_repo.find_by_workspace(workspace_id, limit=1000)
        active_counts: dict[str, int] = {}
        for task in tasks:
            if task.assignee_agent_id and getattr(task.status, "value", task.status) in {
                "todo",
                "in_progress",
                "dispatched",
                "executing",
                "reported",
                "adjudicating",
            }:
                active_counts[task.assignee_agent_id] = (
                    active_counts.get(task.assignee_agent_id, 0) + 1
                )

        pool: list[AllocatorAgent] = []
        for binding in bindings:
            config = dict(binding.config or {})
            tags = _string_set(
                [
                    binding.label,
                    binding.display_name,
                    binding.agent_id,
                    *_iter_config_strings(config.get("affinity_tags")),
                ]
            )
            pool.append(
                AllocatorAgent(
                    agent_id=binding.agent_id,
                    display_name=binding.display_name or binding.label or binding.agent_id,
                    capabilities=_string_set(
                        [
                            *_iter_config_strings(config.get("capabilities")),
                            *_iter_config_strings(config.get("skills")),
                        ]
                    ),
                    tool_names=_string_set(
                        [
                            *_iter_config_strings(config.get("tool_names")),
                            *_iter_config_strings(config.get("tools")),
                            *_iter_config_strings(config.get("allowed_tools")),
                        ]
                    ),
                    active_task_count=active_counts.get(binding.agent_id, 0),
                    is_leader=binding.agent_id == BUILTIN_SISYPHUS_ID,
                    is_available=binding.is_active and binding.status != "offline",
                    affinity_tags=tags,
                )
            )
        return pool

    return _agent_pool


def _make_sql_dispatcher(
    session: AsyncSession,
    item: WorkspacePlanOutboxModel,
    payload: Mapping[str, Any],
) -> Dispatcher:
    async def _dispatch(workspace_id: str, allocation: Allocation, node: PlanNode) -> str | None:
        plan_id = item.plan_id
        if plan_id is None:
            raise ValueError("workspace plan dispatch requires a plan_id")
        root_task_id = await _resolve_root_task_id(session, workspace_id, payload)
        if root_task_id is None:
            raise ValueError("workspace plan dispatch requires a root goal task")

        actor_user_id = await _resolve_actor_user_id(session, workspace_id, payload)
        leader_agent_id = _payload_string(payload, "leader_agent_id") or BUILTIN_SISYPHUS_ID
        binding = await SqlWorkspaceAgentRepository(session).find_by_workspace_and_agent_id(
            workspace_id=workspace_id,
            agent_id=str(allocation.agent_id),
        )
        if binding is None:
            raise ValueError(
                f"workspace agent binding not found for agent_id={allocation.agent_id}"
            )

        task_repo = SqlWorkspaceTaskRepository(session)
        existing_task = await _find_task_for_plan_node(
            session=session,
            workspace_id=workspace_id,
            plan_id=plan_id,
            node_id=node.id,
        )
        task_service = WorkspaceTaskService(
            workspace_repo=SqlWorkspaceRepository(session),
            workspace_member_repo=SqlWorkspaceMemberRepository(session),
            workspace_agent_repo=SqlWorkspaceAgentRepository(session),
            workspace_task_repo=task_repo,
        )
        command_service = WorkspaceTaskCommandService(task_service)
        if existing_task is None:
            existing_task = await command_service.create_task(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                title=node.title,
                description=node.description or None,
                metadata={
                    AUTONOMY_SCHEMA_VERSION_KEY: AUTONOMY_SCHEMA_VERSION,
                    TASK_ROLE: "execution_task",
                    ROOT_GOAL_TASK_ID: root_task_id,
                    LINEAGE_SOURCE: "agent",
                    DERIVED_FROM_INTERNAL_PLAN_STEP: node.id,
                    WORKSPACE_PLAN_ID: plan_id,
                    WORKSPACE_PLAN_NODE_ID: node.id,
                    **_execution_task_metadata_from_node(node),
                },
                priority=WorkspaceTaskPriority.from_rank(min(max(int(node.priority), 0), 4)),
                estimated_effort=(
                    f"{node.estimated_effort.minutes}m"
                    if node.estimated_effort.minutes > 0
                    else None
                ),
                actor_type="agent",
                actor_agent_id=leader_agent_id,
                reason="workspace_plan.dispatch.create_projection_task",
                authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
            )

        if existing_task.assignee_agent_id != binding.agent_id:
            existing_task = await command_service.assign_task_to_agent(
                workspace_id=workspace_id,
                task_id=existing_task.id,
                actor_user_id=actor_user_id,
                workspace_agent_id=binding.id,
                actor_type="agent",
                actor_agent_id=leader_agent_id,
                reason="workspace_plan.dispatch.assign_worker",
                authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
            )

        attempt_service = WorkspaceTaskSessionAttemptService(
            SqlWorkspaceTaskSessionAttemptRepository(session)
        )
        attempt = await attempt_service.get_active_attempt(existing_task.id)
        should_schedule = False
        if attempt is None:
            attempt = await attempt_service.create_attempt(
                workspace_task_id=existing_task.id,
                root_goal_task_id=root_task_id,
                workspace_id=workspace_id,
                worker_agent_id=existing_task.assignee_agent_id,
                leader_agent_id=leader_agent_id,
            )
            attempt = await attempt_service.mark_running(attempt.id)
            should_schedule = True
        elif attempt.status is WorkspaceTaskSessionAttemptStatus.PENDING:
            attempt = await attempt_service.mark_running(attempt.id)
            should_schedule = True

        _apply_attempt_worktree_checkpoint(node, attempt.id)
        await _ensure_root_started_for_dispatch(
            task_service=task_service,
            command_service=command_service,
            workspace_id=workspace_id,
            root_task_id=root_task_id,
            actor_user_id=actor_user_id,
            leader_agent_id=leader_agent_id,
        )
        existing_task = await _project_dispatch_attempt_to_task(
            command_service=command_service,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            task=existing_task,
            attempt=attempt,
            worker_agent_id=binding.agent_id,
            worker_binding_id=binding.id,
            leader_agent_id=leader_agent_id,
            plan_metadata=_execution_task_metadata_from_node(node),
        )

        node.workspace_task_id = existing_task.id
        node.metadata = {
            **dict(node.metadata or {}),
            "workspace_task_id": existing_task.id,
            WORKSPACE_AGENT_BINDING_ID: binding.id,
        }

        await session.flush()
        if should_schedule and existing_task.assignee_agent_id:
            _ = await SqlWorkspacePlanOutboxRepository(session).enqueue(
                plan_id=plan_id,
                workspace_id=workspace_id,
                event_type=WORKER_LAUNCH_EVENT,
                payload={
                    "workspace_id": workspace_id,
                    "node_id": node.id,
                    "task_id": existing_task.id,
                    "worker_agent_id": existing_task.assignee_agent_id,
                    "actor_user_id": actor_user_id,
                    "leader_agent_id": leader_agent_id,
                    "attempt_id": attempt.id,
                    "extra_instructions": _node_worker_brief(node),
                },
                metadata={"source": "workspace_plan.dispatch.worker_launch"},
            )

        return attempt.id

    return _dispatch


def make_worker_launch_handler(
    *,
    worktree_preparer: WorktreePreparer | None = None,
) -> WorkspacePlanOutboxHandler:
    """Build an outbox handler that durably schedules a worker conversation."""

    async def _handle(item: WorkspacePlanOutboxModel, session: AsyncSession) -> None:
        payload = dict(item.payload_json or {})
        workspace_id = _payload_string(payload, "workspace_id") or item.workspace_id
        task_id = _required_payload_string(payload, "task_id")
        worker_agent_id = _payload_string(payload, "worker_agent_id")
        actor_user_id = _required_payload_string(payload, "actor_user_id")
        leader_agent_id = _payload_string(payload, "leader_agent_id")
        attempt_id = _payload_string(payload, "attempt_id")
        extra_instructions = _payload_string(payload, "extra_instructions")

        task = await SqlWorkspaceTaskRepository(session).find_by_id(task_id)
        if task is None or task.workspace_id != workspace_id:
            raise ValueError(f"workspace task {task_id} not found for workspace {workspace_id}")
        resolved_worker_agent_id = worker_agent_id or task.assignee_agent_id
        if not resolved_worker_agent_id:
            raise ValueError(f"workspace task {task_id} has no worker agent")

        setup_note = await _worker_launch_worktree_note(
            worktree_preparer or _prepare_attempt_worktree_if_available,
            session=session,
            workspace_id=workspace_id,
            task=task,
            extra_instructions=extra_instructions,
        )
        extra_instructions = _append_launch_instruction_note(extra_instructions, setup_note)

        from src.infrastructure.agent.workspace.worker_launch import (
            schedule_worker_session,
        )

        schedule_worker_session(
            workspace_id=workspace_id,
            task=task,
            worker_agent_id=resolved_worker_agent_id,
            actor_user_id=actor_user_id,
            leader_agent_id=leader_agent_id,
            attempt_id=attempt_id,
            extra_instructions=extra_instructions,
        )

    return _handle


def make_handoff_resume_handler() -> WorkspacePlanOutboxHandler:
    """Build a handler that turns recovery/retry jobs into fresh worker launches."""

    async def _handle(item: WorkspacePlanOutboxModel, session: AsyncSession) -> None:
        payload = dict(item.payload_json or {})
        workspace_id = _payload_string(payload, "workspace_id") or item.workspace_id
        task_id = _required_payload_string(payload, "task_id")

        task = await SqlWorkspaceTaskRepository(session).find_by_id(task_id)
        if task is None or task.workspace_id != workspace_id:
            raise ValueError(f"workspace task {task_id} not found for workspace {workspace_id}")

        metadata = dict(task.metadata or {})
        actor_user_id = _payload_string(payload, "actor_user_id") or task.created_by
        leader_agent_id = _payload_string(payload, "leader_agent_id") or BUILTIN_SISYPHUS_ID
        worker_agent_id = _payload_string(payload, "worker_agent_id") or task.assignee_agent_id
        if not worker_agent_id:
            raise ValueError(f"workspace task {task_id} has no worker agent")

        root_task_id = (
            _payload_string(payload, ROOT_GOAL_TASK_ID)
            or _payload_string(payload, "root_goal_task_id")
            or _mapping_string(metadata, ROOT_GOAL_TASK_ID)
        )
        if not root_task_id:
            raise ValueError(f"workspace task {task_id} has no root goal task")

        binding = await SqlWorkspaceAgentRepository(session).find_by_workspace_and_agent_id(
            workspace_id=workspace_id,
            agent_id=worker_agent_id,
        )
        if binding is None:
            raise ValueError(f"workspace agent binding not found for agent_id={worker_agent_id}")

        attempt_service = WorkspaceTaskSessionAttemptService(
            SqlWorkspaceTaskSessionAttemptRepository(session)
        )
        attempt = await attempt_service.get_active_attempt(task.id)
        should_schedule = _payload_bool(payload, "force_schedule")
        if attempt is None:
            attempt = await attempt_service.create_attempt(
                workspace_task_id=task.id,
                root_goal_task_id=root_task_id,
                workspace_id=workspace_id,
                worker_agent_id=worker_agent_id,
                leader_agent_id=leader_agent_id,
            )
            attempt = await attempt_service.mark_running(attempt.id)
            should_schedule = True
        elif attempt.status is WorkspaceTaskSessionAttemptStatus.PENDING:
            attempt = await attempt_service.mark_running(attempt.id)
            should_schedule = True
        elif not attempt.conversation_id:
            should_schedule = True

        plan_id = item.plan_id or _mapping_string(metadata, WORKSPACE_PLAN_ID)
        node_id = _payload_string(payload, "node_id") or _mapping_string(
            metadata, WORKSPACE_PLAN_NODE_ID
        )
        handoff = _build_handoff_package(
            event_type=item.event_type,
            payload=payload,
            task=task,
            metadata=metadata,
        )

        node_brief: str | None = None
        plan_metadata: dict[str, object] = {"handoff_package": handoff.to_json()}
        if plan_id and node_id:
            node = await _attach_handoff_to_plan_node(
                session=session,
                plan_id=plan_id,
                node_id=node_id,
                task=task,
                attempt=attempt,
                worker_agent_id=worker_agent_id,
                worker_binding_id=binding.id,
                handoff=handoff,
            )
            if node is not None:
                node_brief = _node_worker_brief(node)
                plan_metadata.update(_execution_task_metadata_from_node(node))

        task_service = WorkspaceTaskService(
            workspace_repo=SqlWorkspaceRepository(session),
            workspace_member_repo=SqlWorkspaceMemberRepository(session),
            workspace_agent_repo=SqlWorkspaceAgentRepository(session),
            workspace_task_repo=SqlWorkspaceTaskRepository(session),
        )
        command_service = WorkspaceTaskCommandService(task_service)
        task = await _project_dispatch_attempt_to_task(
            command_service=command_service,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            task=task,
            attempt=attempt,
            worker_agent_id=worker_agent_id,
            worker_binding_id=binding.id,
            leader_agent_id=leader_agent_id,
            plan_metadata=plan_metadata,
        )

        await session.flush()
        if not should_schedule:
            return
        extra_instructions = _append_launch_instruction_note(
            _payload_string(payload, "extra_instructions"),
            node_brief or _handoff_only_brief(handoff),
        )
        _ = await SqlWorkspacePlanOutboxRepository(session).enqueue(
            plan_id=plan_id,
            workspace_id=workspace_id,
            event_type=WORKER_LAUNCH_EVENT,
            payload={
                "workspace_id": workspace_id,
                "node_id": node_id,
                "task_id": task.id,
                "worker_agent_id": worker_agent_id,
                "actor_user_id": actor_user_id,
                "leader_agent_id": leader_agent_id,
                "attempt_id": attempt.id,
                "extra_instructions": extra_instructions,
            },
            metadata={
                "source": f"workspace_plan.{item.event_type}",
                "previous_attempt_id": _payload_string(payload, "previous_attempt_id"),
            },
        )

    return _handle


def make_attempt_retry_handler() -> WorkspacePlanOutboxHandler:
    """Build a retry handler; retry and handoff resume share the same durable path."""

    return make_handoff_resume_handler()


async def _attach_handoff_to_plan_node(
    *,
    session: AsyncSession,
    plan_id: str,
    node_id: str,
    task: WorkspaceTask,
    attempt: WorkspaceTaskSessionAttempt,
    worker_agent_id: str,
    worker_binding_id: str,
    handoff: HandoffPackage,
) -> PlanNode | None:
    plan = await SqlPlanRepository(session).get(plan_id)
    if plan is None:
        return None
    node = plan.nodes.get(PlanNodeId(node_id))
    if node is None:
        return None

    node.workspace_task_id = task.id
    node.current_attempt_id = attempt.id
    node.assignee_agent_id = worker_agent_id
    node.intent = TaskIntent.IN_PROGRESS
    node.execution = TaskExecution.RUNNING
    node.handoff_package = handoff
    node.metadata = {
        **dict(node.metadata or {}),
        "workspace_task_id": task.id,
        WORKSPACE_AGENT_BINDING_ID: worker_binding_id,
    }
    _apply_attempt_worktree_checkpoint(node, attempt.id)
    plan.replace_node(node)
    await SqlPlanRepository(session).save(plan)
    return node


def _build_handoff_package(
    *,
    event_type: str,
    payload: Mapping[str, Any],
    task: WorkspaceTask,
    metadata: Mapping[str, Any],
) -> HandoffPackage:
    summary = (
        _payload_string(payload, "summary")
        or _mapping_string(metadata, LAST_WORKER_REPORT_SUMMARY)
        or f"Resume workspace task after {event_type}."
    )
    previous_attempt_id = _payload_string(payload, "previous_attempt_id")
    completed_steps = [
        value
        for value in (
            f"previous_attempt_id={previous_attempt_id}" if previous_attempt_id else None,
            f"last_report={_mapping_string(metadata, 'last_worker_report_type')}"
            if _mapping_string(metadata, "last_worker_report_type")
            else None,
        )
        if value
    ]
    return HandoffPackage(
        reason=_handoff_reason_for_event(event_type, _payload_string(payload, "reason")),
        summary=summary,
        completed_steps=tuple(completed_steps),
        next_steps=(
            "Inspect the checkpoint, existing worktree, recent git status, and any prior diff.",
            "Continue from the durable plan node and report completion with evidence.",
        ),
        changed_files=tuple(_prefixed_metadata_values(metadata, "changed_file:")),
        git_head=_first_prefixed_metadata_value(metadata, "commit_ref:"),
        git_diff_summary=_first_prefixed_metadata_value(metadata, "git_diff_summary:") or "",
        test_commands=tuple(_known_test_commands(metadata)),
        verification_notes=_verification_notes(metadata) or "",
    )


def _handoff_reason_for_event(event_type: str, raw_reason: str | None) -> HandoffReason:
    if raw_reason:
        with contextlib.suppress(ValueError):
            return HandoffReason(raw_reason)
    if event_type == ATTEMPT_RETRY_EVENT:
        return HandoffReason.RETRY
    return HandoffReason.WORKER_RESTART


def _handoff_only_brief(handoff: HandoffPackage) -> str:
    lines = [
        "[handoff-package]",
        f"reason={handoff.reason.value}",
        f"created_at={handoff.created_at.isoformat()}",
        f"summary={handoff.summary}",
    ]
    lines.extend(f"completed_step={step}" for step in handoff.completed_steps)
    lines.extend(f"next_step={step}" for step in handoff.next_steps)
    lines.extend(f"changed_file={path}" for path in handoff.changed_files)
    lines.extend(f"test_command={command}" for command in handoff.test_commands)
    lines.append("[/handoff-package]")
    lines.extend(_rehydration_guidance_lines())
    return "\n".join(lines)


def _prefixed_metadata_values(metadata: Mapping[str, Any], prefix: str) -> list[str]:
    return [
        value.removeprefix(prefix)
        for value in _metadata_string_values(metadata, "evidence_refs")
        if value.startswith(prefix)
    ]


def _first_prefixed_metadata_value(metadata: Mapping[str, Any], prefix: str) -> str | None:
    for value in _metadata_string_values(metadata, "evidence_refs"):
        if value.startswith(prefix):
            return value.removeprefix(prefix)
    return None


def _known_test_commands(metadata: Mapping[str, Any]) -> list[str]:
    commands: list[str] = []
    commands.extend(_metadata_string_values(metadata, "verification_commands"))
    commands.extend(
        value.removeprefix("test_run:")
        for value in _metadata_string_values(metadata, "execution_verifications")
        if value.startswith("test_run:")
    )
    feature = metadata.get("feature_checkpoint")
    if isinstance(feature, Mapping):
        commands.extend(_iter_config_strings(feature.get("test_commands")))
    return list(dict.fromkeys(command for command in commands if command))


def _verification_notes(metadata: Mapping[str, Any]) -> str | None:
    verifications = _metadata_string_values(metadata, "execution_verifications")
    if not verifications:
        return None
    return "; ".join(verifications[:8])


def _metadata_string_values(metadata: Mapping[str, Any], key: str) -> list[str]:
    value = metadata.get(key)
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return []


async def _worker_launch_worktree_note(
    preparer: WorktreePreparer,
    *,
    session: AsyncSession,
    workspace_id: str,
    task: WorkspaceTask,
    extra_instructions: str | None,
) -> str | None:
    try:
        return await preparer(session, workspace_id, task, extra_instructions)
    except Exception as exc:
        logger.warning(
            "workspace_plan.worker_launch.worktree_prepare_failed",
            extra={
                "event": "workspace_plan.worker_launch.worktree_prepare_failed",
                "workspace_id": workspace_id,
                "task_id": task.id,
            },
            exc_info=True,
        )
        return _worktree_setup_note(status="failed", reason=f"preparer raised: {exc}")


def _append_launch_instruction_note(instructions: str | None, note: str | None) -> str | None:
    if not note:
        return instructions
    if not instructions:
        return note.strip()
    return f"{instructions.rstrip()}\n\n{note.strip()}"


async def _prepare_attempt_worktree_if_available(  # noqa: PLR0911
    session: AsyncSession,
    workspace_id: str,
    task: WorkspaceTask,
    _extra_instructions: str | None,
) -> str | None:
    metadata = dict(task.metadata or {})
    feature_checkpoint = metadata.get("feature_checkpoint")
    if not isinstance(feature_checkpoint, Mapping):
        return None
    feature_metadata = cast(Mapping[str, Any], feature_checkpoint)

    worktree_path_template = _mapping_string(feature_metadata, "worktree_path")
    branch_name = _mapping_string(feature_metadata, "branch_name")
    base_ref = _mapping_string(feature_metadata, "base_ref") or "HEAD"
    if not worktree_path_template or not branch_name:
        return _worktree_setup_note(
            status="skipped",
            reason="feature checkpoint does not include worktree_path and branch_name",
        )

    workspace = await SqlWorkspaceRepository(session).find_by_id(workspace_id)
    if workspace is None:
        return _worktree_setup_note(status="skipped", reason="workspace not found")

    root_metadata: Mapping[str, Any] = {}
    root_task_id = _mapping_string(metadata, ROOT_GOAL_TASK_ID)
    if root_task_id:
        root_task = await SqlWorkspaceTaskRepository(session).find_by_id(root_task_id)
        if root_task is not None and root_task.workspace_id == workspace_id:
            root_metadata = dict(root_task.metadata or {})

    from src.infrastructure.agent.workspace.code_context import (
        load_workspace_code_context,
    )

    workspace_metadata = dict(getattr(workspace, "metadata", {}) or {})
    code_context = load_workspace_code_context(
        project_id=workspace.project_id,
        root_metadata=root_metadata,
        workspace_metadata=workspace_metadata,
    )
    if not code_context.sandbox_code_root:
        return _worktree_setup_note(
            status="skipped",
            reason="sandbox_code_root is not available for this workspace",
        )

    worktree_path = worktree_path_template.replace(
        "${sandbox_code_root}", code_context.sandbox_code_root
    )
    if "${sandbox_code_root}" in worktree_path:
        return _worktree_setup_note(
            status="skipped",
            reason="worktree_path still contains an unresolved sandbox_code_root placeholder",
        )

    command = _worktree_setup_command(
        sandbox_code_root=code_context.sandbox_code_root,
        worktree_path=worktree_path,
        branch_name=branch_name,
        base_ref=base_ref,
    )
    try:
        result = await _WorkspaceSandboxCommandRunner(project_id=workspace.project_id).run_command(
            command,
            timeout=120,
        )
    except Exception as exc:
        return _worktree_setup_note(
            status="failed",
            reason=str(exc),
            worktree_path=worktree_path,
            branch_name=branch_name,
            base_ref=base_ref,
        )

    stdout = str(result.get("stdout") or "")
    stderr = str(result.get("stderr") or "")
    if int(result.get("exit_code") or 0) != 0:
        return _worktree_setup_note(
            status="failed",
            reason=_compact_command_output(stderr or stdout),
            worktree_path=worktree_path,
            branch_name=branch_name,
            base_ref=base_ref,
        )
    return _worktree_setup_note(
        status="prepared",
        output=_compact_command_output(stdout),
        worktree_path=worktree_path,
        branch_name=branch_name,
        base_ref=base_ref,
    )


def _worktree_setup_command(
    *,
    sandbox_code_root: str,
    worktree_path: str,
    branch_name: str,
    base_ref: str,
) -> str:
    code_root = shlex.quote(sandbox_code_root)
    worktree = shlex.quote(worktree_path)
    branch = shlex.quote(branch_name)
    base = shlex.quote(base_ref)
    return "\n".join(
        [
            "set -e",
            f"cd {code_root}",
            f'mkdir -p "$(dirname {worktree})"',
            f"if [ -e {worktree}/.git ] || [ -f {worktree}/.git ]; then",
            f"  git -C {worktree} checkout {branch}",
            "else",
            f"  git worktree add -B {branch} {worktree} {base}",
            "fi",
            f'printf "git_head=%s\\n" "$(git -C {worktree} rev-parse HEAD)"',
            f"git -C {worktree} status --short",
            f"git -C {worktree} diff --stat -- || true",
        ]
    )


def _worktree_setup_note(
    *,
    status: str,
    reason: str | None = None,
    output: str | None = None,
    worktree_path: str | None = None,
    branch_name: str | None = None,
    base_ref: str | None = None,
) -> str:
    lines = ["[worktree-setup]", f"status={status}"]
    if worktree_path:
        lines.append(f"worktree_path={worktree_path}")
    if branch_name:
        lines.append(f"branch_name={branch_name}")
    if base_ref:
        lines.append(f"base_ref={base_ref}")
    if reason:
        lines.append(f"reason={_compact_command_output(reason)}")
    if output:
        lines.append(f"output={_compact_command_output(output)}")
    lines.append("[/worktree-setup]")
    return "\n".join(lines)


def _compact_command_output(value: str, *, limit: int = 1000) -> str:
    compacted = value.strip().replace("\n", "\\n")
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 15] + "...[truncated]"


async def _ensure_root_started_for_dispatch(
    *,
    task_service: WorkspaceTaskService,
    command_service: WorkspaceTaskCommandService,
    workspace_id: str,
    root_task_id: str,
    actor_user_id: str,
    leader_agent_id: str,
) -> None:
    root_task = await task_service.get_task(
        workspace_id=workspace_id,
        task_id=root_task_id,
        actor_user_id=actor_user_id,
    )
    if root_task.status is not WorkspaceTaskStatus.TODO:
        return
    _ = await command_service.start_task(
        workspace_id=workspace_id,
        task_id=root_task.id,
        actor_user_id=actor_user_id,
        actor_type="agent",
        actor_agent_id=leader_agent_id,
        reason="workspace_plan.dispatch.start_root",
        authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
    )


async def _project_dispatch_attempt_to_task(
    *,
    command_service: WorkspaceTaskCommandService,
    workspace_id: str,
    actor_user_id: str,
    task: WorkspaceTask,
    attempt: WorkspaceTaskSessionAttempt,
    worker_agent_id: str,
    worker_binding_id: str,
    leader_agent_id: str,
    plan_metadata: Mapping[str, object] | None = None,
) -> WorkspaceTask:
    """Synchronize a durable dispatch onto the workspace task projection.

    Durable V2 is the source of truth, while the blackboard UI reads projected
    ``WorkspaceTask`` rows. Project the running attempt before
    the async worker launcher fills in conversation details so dispatched work
    never appears stuck at TODO.
    """

    metadata_patch: dict[str, object] = {
        **dict(plan_metadata or {}),
        CURRENT_ATTEMPT_ID: attempt.id,
        "current_attempt_number": attempt.attempt_number,
        "current_attempt_worker_agent_id": worker_agent_id,
        CURRENT_ATTEMPT_WORKER_BINDING_ID: worker_binding_id,
        "last_attempt_status": WorkspaceTaskSessionAttemptStatus.RUNNING.value,
        "launch_state": "scheduled",
        EXECUTION_STATE: _build_dispatch_execution_state(actor_id=leader_agent_id),
    }
    task_status = task.status.value
    target_status = WorkspaceTaskStatus.IN_PROGRESS if task_status != "done" else None
    return await command_service.update_task(
        workspace_id=workspace_id,
        task_id=task.id,
        actor_user_id=actor_user_id,
        status=target_status,
        metadata=metadata_patch,
        actor_type="agent",
        actor_agent_id=leader_agent_id,
        workspace_agent_binding_id=worker_binding_id,
        reason="workspace_plan.dispatch.project_attempt",
        authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
    )


def _make_sql_attempt_context(session: AsyncSession) -> AttemptContextProvider:
    async def _attempt_context(workspace_id: str, node: PlanNode) -> VerificationContext:
        stdout = ""
        artifacts: dict[str, Any] = {}
        sandbox: _WorkspaceSandboxCommandRunner | None = None
        workspace = await SqlWorkspaceRepository(session).find_by_id(workspace_id)
        if workspace is not None and getattr(workspace, "project_id", None):
            sandbox = _WorkspaceSandboxCommandRunner(project_id=workspace.project_id)
        if node.workspace_task_id:
            task = await SqlWorkspaceTaskRepository(session).find_by_id(node.workspace_task_id)
            if task is not None:
                stdout, artifacts = _extract_task_evidence(task)

        if node.current_attempt_id:
            attempt = await SqlWorkspaceTaskSessionAttemptRepository(session).find_by_id(
                node.current_attempt_id
            )
            if attempt is not None:
                stdout = attempt.candidate_summary or stdout
                if attempt.candidate_artifacts:
                    artifacts["candidate_artifacts"] = list(attempt.candidate_artifacts)
                if attempt.candidate_verifications:
                    artifacts["candidate_verifications"] = list(attempt.candidate_verifications)

        return VerificationContext(
            workspace_id=workspace_id,
            node=node,
            attempt_id=node.current_attempt_id,
            artifacts=artifacts,
            stdout=stdout,
            sandbox=sandbox,
        )

    return _attempt_context


class _WorkspaceSandboxCommandRunner:
    """Small adapter that lets durable criteria run commands in the project sandbox."""

    def __init__(self, *, project_id: str) -> None:
        self._project_id = project_id

    async def run_command(self, command: str, *, timeout: int = 60) -> dict[str, Any]:
        from src.infrastructure.agent.state.agent_worker_state import (
            _resolve_project_sandbox_id,
            get_mcp_sandbox_adapter,
        )

        adapter = get_mcp_sandbox_adapter()
        if adapter is None:
            raise RuntimeError("MCP sandbox adapter is not initialized")
        sandbox_id = await _resolve_project_sandbox_id(self._project_id)
        if not sandbox_id:
            raise RuntimeError(f"no sandbox found for project {self._project_id}")

        raw = await adapter.call_tool(
            sandbox_id,
            "bash",
            {
                "command": command,
                "timeout": timeout,
            },
            timeout=float(timeout) + 5.0,
        )
        text = _tool_result_text(raw)
        is_error = bool(raw.get("is_error") or raw.get("isError"))
        return {
            "exit_code": 1 if is_error else 0,
            "stdout": "" if is_error else text,
            "stderr": text if is_error else "",
        }


async def _resolve_root_task_id(
    session: AsyncSession,
    workspace_id: str,
    payload: Mapping[str, Any],
) -> str | None:
    direct = _payload_string(payload, "root_task_id") or _payload_string(payload, ROOT_GOAL_TASK_ID)
    if direct:
        return direct
    stmt = (
        select(WorkspaceTaskModel)
        .where(WorkspaceTaskModel.workspace_id == workspace_id)
        .where(WorkspaceTaskModel.metadata_json[TASK_ROLE].as_string() == "goal_root")
        .where(WorkspaceTaskModel.archived_at.is_(None))
        .order_by(WorkspaceTaskModel.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    return row.id if row is not None else None


async def _resolve_actor_user_id(
    session: AsyncSession,
    workspace_id: str,
    payload: Mapping[str, Any],
) -> str:
    direct = _payload_string(payload, "actor_user_id") or _payload_string(payload, "created_by")
    if direct:
        return direct
    workspace = await SqlWorkspaceRepository(session).find_by_id(workspace_id)
    if workspace is None:
        raise ValueError(f"Workspace {workspace_id} not found")
    return workspace.created_by


async def _find_task_for_plan_node(
    *,
    session: AsyncSession,
    workspace_id: str,
    plan_id: str,
    node_id: str,
) -> WorkspaceTask | None:
    stmt = (
        select(WorkspaceTaskModel)
        .where(WorkspaceTaskModel.workspace_id == workspace_id)
        .where(WorkspaceTaskModel.metadata_json[WORKSPACE_PLAN_ID].as_string() == plan_id)
        .where(WorkspaceTaskModel.metadata_json[WORKSPACE_PLAN_NODE_ID].as_string() == node_id)
        .where(WorkspaceTaskModel.archived_at.is_(None))
        .order_by(WorkspaceTaskModel.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.scalar_one_or_none()
    return SqlWorkspaceTaskRepository(session)._to_domain(row)


def _extract_task_evidence(task: WorkspaceTask) -> tuple[str, dict[str, Any]]:
    metadata = dict(task.metadata or {})
    summary = metadata.get(LAST_WORKER_REPORT_SUMMARY)
    stdout = summary if isinstance(summary, str) else json.dumps(summary or "", ensure_ascii=False)
    artifacts: dict[str, Any] = {}
    for key in (
        "evidence_refs",
        "execution_verifications",
        "last_worker_report_artifacts",
        "last_worker_report_verifications",
    ):
        value = metadata.get(key)
        if isinstance(value, list):
            artifacts[key] = [str(item) for item in value if item]
    for key in (
        "current_attempt_conversation_id",
        "last_attempt_status",
        "last_worker_report_summary",
        "last_worker_report_type",
    ):
        value = metadata.get(key)
        if isinstance(value, str) and value:
            artifacts[key] = value
    return stdout, artifacts


def _execution_task_metadata_from_node(node: PlanNode) -> dict[str, object]:
    metadata: dict[str, object] = {}
    if node.feature_checkpoint is not None:
        metadata["feature_checkpoint"] = node.feature_checkpoint.to_json()
    if node.handoff_package is not None:
        metadata["handoff_package"] = node.handoff_package.to_json()
    write_set = node.metadata.get("write_set")
    if isinstance(write_set, list):
        metadata["write_set"] = [str(item) for item in write_set if item]
    commands = node.metadata.get("verification_commands")
    if isinstance(commands, list):
        metadata["verification_commands"] = [str(item) for item in commands if item]
    return metadata


def _apply_attempt_worktree_checkpoint(node: PlanNode, attempt_id: str) -> None:
    feature = node.feature_checkpoint
    if feature is None:
        return
    branch_name = feature.branch_name or _worktree_branch_name(
        node_id=node.id, attempt_id=attempt_id
    )
    worktree_path = (
        feature.worktree_path or f"${{sandbox_code_root}}/../.memstack/worktrees/{attempt_id}"
    )
    node.feature_checkpoint = replace(
        feature,
        worktree_path=worktree_path,
        branch_name=branch_name,
        base_ref=feature.base_ref or "HEAD",
    )


def _worktree_branch_name(*, node_id: str, attempt_id: str) -> str:
    node_token = _safe_git_token(node_id)[:48]
    attempt_token = _safe_git_token(attempt_id)[:12]
    return f"workspace/{node_token}-{attempt_token}"


def _safe_git_token(value: str) -> str:
    token = "".join(ch if ch.isalnum() or ch in "._-" else "-" for ch in value)
    token = token.strip("./-")
    return token or "node"


def _tool_result_text(raw: Mapping[str, Any]) -> str:
    content = raw.get("content")
    if isinstance(content, list):
        parts = [
            str(item.get("text") or "")
            for item in content
            if isinstance(item, Mapping) and item.get("text")
        ]
        if parts:
            return "\n".join(parts)
    output = raw.get("output")
    if isinstance(output, str):
        return output
    text = raw.get("text")
    if isinstance(text, str):
        return text
    return ""


def _node_worker_brief(node: PlanNode) -> str:
    lines = [
        "[workspace-plan-node]",
        f"plan_id={node.plan_id}",
        f"node_id={node.id}",
        f"title={node.title}",
    ]
    lines.extend(_feature_checkpoint_brief_lines(node))
    lines.extend(_handoff_package_brief_lines(node))
    lines.extend(_rehydration_guidance_lines())
    if node.description:
        lines.extend(["", str(node.description)])
    return "\n".join(lines)


def _feature_checkpoint_brief_lines(node: PlanNode) -> list[str]:
    feature = node.feature_checkpoint
    if feature is None:
        return []
    lines = [
        "",
        "[feature-checkpoint]",
        f"feature_id={feature.feature_id}",
        f"sequence={feature.sequence}",
        f"title={feature.title or node.title}",
    ]
    if feature.init_command:
        lines.append(f"init_command={feature.init_command}")
    if feature.commit_ref:
        lines.append(f"commit_ref={feature.commit_ref}")
    if feature.worktree_path:
        lines.append(f"worktree_path={feature.worktree_path}")
    if feature.branch_name:
        lines.append(f"branch_name={feature.branch_name}")
    if feature.base_ref:
        lines.append(f"base_ref={feature.base_ref}")
    lines.extend(f"test_command={command}" for command in feature.test_commands)
    lines.extend(f"expected_artifact={artifact}" for artifact in feature.expected_artifacts)
    if feature.handoff_notes:
        lines.append(f"handoff_notes={feature.handoff_notes}")
    lines.append("[/feature-checkpoint]")
    return lines


def _handoff_package_brief_lines(node: PlanNode) -> list[str]:
    handoff = node.handoff_package
    if handoff is None:
        return []
    lines = [
        "",
        "[handoff-package]",
        f"reason={handoff.reason.value}",
        f"created_at={handoff.created_at.isoformat()}",
        f"summary={handoff.summary}",
    ]
    if handoff.git_head:
        lines.append(f"git_head={handoff.git_head}")
    if handoff.git_diff_summary:
        lines.append(f"git_diff_summary={handoff.git_diff_summary}")
    if handoff.verification_notes:
        lines.append(f"verification_notes={handoff.verification_notes}")
    lines.extend(f"completed_step={step}" for step in handoff.completed_steps)
    lines.extend(f"next_step={step}" for step in handoff.next_steps)
    lines.extend(f"changed_file={path}" for path in handoff.changed_files)
    lines.extend(f"test_command={command}" for command in handoff.test_commands)
    lines.append("[/handoff-package]")
    return lines


def _rehydration_guidance_lines() -> list[str]:
    return [
        "",
        (
            "Before changing files, get up to speed from the checkpoint: inspect git status, "
            "recent commits, existing diffs, and any listed test commands from the code root."
        ),
        (
            "If a worktree_path is listed, create or reuse that git worktree from base_ref, "
            "switch to branch_name, and perform edits/tests there instead of the main checkout."
        ),
        (
            "When reporting completion, include artifacts, verification evidence, remaining risk, "
            "commit_ref, changed_file entries, test_run evidence, and any diff summary needed by "
            "the next worker."
        ),
    ]


def _payload_string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _mapping_string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _payload_bool(payload: Mapping[str, Any], key: str) -> bool:
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _required_payload_string(payload: Mapping[str, Any], key: str) -> str:
    value = _payload_string(payload, key)
    if value is None:
        raise ValueError(f"worker launch payload requires {key}")
    return value


def _iter_config_strings(value: object) -> Iterable[str]:
    if isinstance(value, str) and value:
        yield value
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, dict)):
        for item in value:
            if isinstance(item, str) and item:
                yield item


def _string_set(values: Iterable[str | None]) -> frozenset[str]:
    return frozenset(str(value).strip().lower() for value in values if value and str(value).strip())


__all__ = [
    "ATTEMPT_RETRY_EVENT",
    "HANDOFF_RESUME_EVENT",
    "SUPERVISOR_TICK_EVENT",
    "WORKER_LAUNCH_EVENT",
    "make_attempt_retry_handler",
    "make_handoff_resume_handler",
    "make_supervisor_tick_handler",
    "make_worker_launch_handler",
]
