"""Workspace-backed /goal command implementation."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from src.application.services.workspace_agent_autonomy import (
    build_workspace_harness_contract,
)
from src.application.services.workspace_task_command_service import WorkspaceTaskCommandService
from src.application.services.workspace_task_event_publisher import WorkspaceTaskEventPublisher
from src.application.services.workspace_task_service import WorkspaceTaskService
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
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
from src.infrastructure.agent.workspace.workspace_metadata_keys import (
    AUTONOMY_SCHEMA_VERSION_KEY,
    PREFERRED_LANGUAGE,
    REPLAN_ATTEMPT_COUNT,
    TASK_ROLE,
    WORKSPACE_HARNESS,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class GoalCommandOutcome:
    """Result of applying a workspace-backed goal command."""

    root_task_id: str
    workspace_id: str
    scheduled: bool


@dataclass(frozen=True, slots=True)
class GoalStatusItem:
    """Projected workspace root goal status for the slash command reply."""

    root_task_id: str
    title: str
    status: str


def resolve_workspace_id(context: Mapping[str, Any]) -> str | None:
    """Read the current workspace id from command/runtime context."""

    runtime_context = _string_mapping(context.get("runtime_context"))
    if isinstance(runtime_context, Mapping):
        workspace_id = _clean_string(runtime_context.get("workspace_id"))
        if workspace_id:
            return workspace_id
        binding = _string_mapping(runtime_context.get("workspace_binding"))
        if isinstance(binding, Mapping):
            workspace_id = _clean_string(binding.get("workspace_id"))
            if workspace_id:
                return workspace_id

    return _clean_string(context.get("workspace_id"))


def resolve_preferred_language(context: Mapping[str, Any]) -> str | None:
    runtime_context = _string_mapping(context.get("runtime_context"))
    if isinstance(runtime_context, Mapping):
        preferred_language = _clean_string(runtime_context.get(PREFERRED_LANGUAGE))
        if preferred_language in {"en-US", "zh-CN"}:
            return preferred_language
    preferred_language = _clean_string(context.get(PREFERRED_LANGUAGE))
    return preferred_language if preferred_language in {"en-US", "zh-CN"} else None


async def create_workspace_goal(
    *,
    workspace_id: str,
    actor_user_id: str,
    goal_text: str,
    conversation_id: str | None = None,
    preferred_language: str | None = None,
) -> GoalCommandOutcome:
    """Create a human-defined workspace root goal and schedule its first tick."""

    async with async_session_factory() as db:
        task_repo = SqlWorkspaceTaskRepository(db)
        task_service = WorkspaceTaskService(
            workspace_repo=SqlWorkspaceRepository(db),
            workspace_member_repo=SqlWorkspaceMemberRepository(db),
            workspace_agent_repo=SqlWorkspaceAgentRepository(db),
            workspace_task_repo=task_repo,
        )
        command_service = WorkspaceTaskCommandService(task_service)
        metadata = build_human_goal_metadata(
            goal_text=goal_text,
            conversation_id=conversation_id,
            preferred_language=preferred_language,
        )
        try:
            task = await command_service.create_task(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                title=goal_text,
                description=goal_text,
                metadata=metadata,
                actor_type="human",
                reason="slash_goal.create",
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

        await _publish_goal_events(command_service)
        scheduled = _schedule_pending_ticks(command_service)
        return GoalCommandOutcome(
            root_task_id=task.id,
            workspace_id=task.workspace_id,
            scheduled=scheduled,
        )


async def list_workspace_goals(
    *,
    workspace_id: str,
    actor_user_id: str,
    limit: int = 5,
) -> list[GoalStatusItem]:
    """List visible workspace root goals for the current user."""

    async with async_session_factory() as db:
        task_service = WorkspaceTaskService(
            workspace_repo=SqlWorkspaceRepository(db),
            workspace_member_repo=SqlWorkspaceMemberRepository(db),
            workspace_agent_repo=SqlWorkspaceAgentRepository(db),
            workspace_task_repo=SqlWorkspaceTaskRepository(db),
        )
        tasks = await task_service.list_tasks(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            limit=100,
            offset=0,
        )

    goals: list[GoalStatusItem] = []
    for task in tasks:
        metadata = dict(task.metadata or {})
        if metadata.get(TASK_ROLE) != "goal_root" or task.archived_at is not None:
            continue
        goals.append(
            GoalStatusItem(
                root_task_id=task.id,
                title=task.title,
                status=_task_status_value(task.status),
            )
        )
        if len(goals) >= limit:
            break
    return goals


def build_human_goal_metadata(
    *,
    goal_text: str,
    conversation_id: str | None,
    preferred_language: str | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        AUTONOMY_SCHEMA_VERSION_KEY: 1,
        TASK_ROLE: "goal_root",
        "goal_origin": "human_defined",
        "goal_source_refs": [f"conversation:{conversation_id}"] if conversation_id else [],
        "goal_formalization_reason": "explicit /goal command",
        "root_goal_policy": {
            "mutable_by_agent": False,
            "completion_requires_external_proof": True,
        },
        "goal_health": "healthy",
        REPLAN_ATTEMPT_COUNT: 0,
        WORKSPACE_HARNESS: build_workspace_harness_contract(goal_title=goal_text),
    }
    if preferred_language in {"en-US", "zh-CN"}:
        metadata[PREFERRED_LANGUAGE] = preferred_language
    return metadata


async def _publish_goal_events(command_service: WorkspaceTaskCommandService) -> None:
    try:
        from src.infrastructure.agent.state.agent_worker_state import get_redis_client

        publisher = WorkspaceTaskEventPublisher(await get_redis_client())
        await publisher.publish_pending_events(command_service.consume_pending_events())
    except Exception:
        logger.warning("/goal created a root task but failed to publish events", exc_info=True)


def _schedule_pending_ticks(command_service: WorkspaceTaskCommandService) -> bool:
    scheduled = False
    for workspace_id, actor_user_id in command_service.consume_pending_autonomy_ticks():
        try:
            from src.infrastructure.adapters.primary.web.routers.workspace_leader_bootstrap import (
                schedule_autonomy_tick,
            )

            schedule_autonomy_tick(workspace_id, actor_user_id)
            scheduled = True
        except Exception:
            logger.warning(
                "/goal created a root task but failed to schedule autonomy tick",
                exc_info=True,
                extra={"workspace_id": workspace_id},
            )
    return scheduled


def _clean_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _task_status_value(value: object) -> str:
    status_value = getattr(value, "value", value)
    return status_value if isinstance(status_value, str) else str(status_value)


def _string_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast("Mapping[str, object]", value)
