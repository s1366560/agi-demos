"""Handlers for durable workspace plan outbox jobs."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

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
from src.domain.model.workspace_plan import PlanNode
from src.domain.ports.services.task_allocator_port import (
    Allocation,
    WorkspaceAgent as AllocatorAgent,
)
from src.domain.ports.services.verifier_port import VerificationContext
from src.infrastructure.adapters.secondary.persistence.models import (
    WorkspacePlanOutboxModel,
    WorkspaceTaskModel,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_agent_repository import (
    SqlWorkspaceAgentRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_member_repository import (
    SqlWorkspaceMemberRepository,
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
logger = logging.getLogger(__name__)


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
                active_counts[task.assignee_agent_id] = active_counts.get(task.assignee_agent_id, 0) + 1

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
            raise ValueError(f"workspace agent binding not found for agent_id={allocation.agent_id}")

        task_repo = SqlWorkspaceTaskRepository(session)
        existing_task = await _find_task_for_plan_node(
            session=session,
            workspace_id=workspace_id,
            plan_id=item.plan_id,
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
                    WORKSPACE_PLAN_ID: item.plan_id,
                    WORKSPACE_PLAN_NODE_ID: node.id,
                },
                priority=WorkspaceTaskPriority.from_rank(min(max(int(node.priority), 0), 4)),
                estimated_effort=(
                    f"{node.estimated_effort.minutes}m"
                    if node.estimated_effort.minutes > 0
                    else None
                ),
                actor_type="agent",
                actor_agent_id=leader_agent_id,
                reason="workspace_plan.dispatch.create_compat_task",
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
        )

        node.workspace_task_id = existing_task.id
        node.metadata = {
            **dict(node.metadata or {}),
            "workspace_task_id": existing_task.id,
            WORKSPACE_AGENT_BINDING_ID: binding.id,
        }

        await session.flush()
        if should_schedule and existing_task.assignee_agent_id:
            await session.commit()
            from src.infrastructure.agent.workspace.worker_launch import (
                schedule_worker_session,
            )

            schedule_worker_session(
                workspace_id=workspace_id,
                task=existing_task,
                worker_agent_id=existing_task.assignee_agent_id,
                actor_user_id=actor_user_id,
                leader_agent_id=leader_agent_id,
                attempt_id=attempt.id,
                extra_instructions=_node_worker_brief(node),
            )

        return attempt.id

    return _dispatch


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
) -> WorkspaceTask:
    """Synchronize a durable dispatch onto the legacy task projection.

    Durable V2 is the source of truth, but the blackboard UI still reads the
    compatibility ``WorkspaceTask`` rows. Project the running attempt before
    the async worker launcher fills in conversation details so dispatched work
    never appears stuck at TODO.
    """

    metadata_patch: dict[str, object] = {
        CURRENT_ATTEMPT_ID: attempt.id,
        "current_attempt_number": attempt.attempt_number,
        "current_attempt_worker_agent_id": worker_agent_id,
        CURRENT_ATTEMPT_WORKER_BINDING_ID: worker_binding_id,
        "last_attempt_status": WorkspaceTaskSessionAttemptStatus.RUNNING.value,
        EXECUTION_STATE: _build_dispatch_execution_state(actor_id=leader_agent_id),
    }
    target_status = (
        WorkspaceTaskStatus.IN_PROGRESS
        if task.status in {WorkspaceTaskStatus.TODO, WorkspaceTaskStatus.BLOCKED}
        else None
    )
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
        )

    return _attempt_context


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
    for key in ("evidence_refs", "execution_verifications", "last_worker_report_artifacts"):
        value = metadata.get(key)
        if isinstance(value, list):
            artifacts[key] = [str(item) for item in value if item]
    return stdout, artifacts


def _node_worker_brief(node: PlanNode) -> str:
    lines = [
        "[workspace-plan-node]",
        f"plan_id={node.plan_id}",
        f"node_id={node.id}",
        f"title={node.title}",
    ]
    if node.description:
        lines.extend(["", str(node.description)])
    return "\n".join(lines)


def _payload_string(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _iter_config_strings(value: object) -> Iterable[str]:
    if isinstance(value, str) and value:
        yield value
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, dict)):
        for item in value:
            if isinstance(item, str) and item:
                yield item


def _string_set(values: Iterable[str | None]) -> frozenset[str]:
    return frozenset(str(value).strip().lower() for value in values if value and str(value).strip())


__all__ = ["SUPERVISOR_TICK_EVENT", "make_supervisor_tick_handler"]
