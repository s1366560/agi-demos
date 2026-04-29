"""Todo tools for ReAct agent.

DB-persistent task management. The agent uses todoread/todowrite to create,
update, and track a task checklist per conversation. Tasks are stored in
PostgreSQL and streamed to the frontend via SSE events.
"""

from __future__ import annotations

import inspect
import json
import logging
import uuid
from collections.abc import Callable
from typing import Any

from src.application.services.workspace_task_service import (
    WorkspaceTaskAuthorityContext,
    WorkspaceTaskService,
)
from src.domain.model.agent.task import AgentTask, TaskPriority, TaskStatus
from src.domain.model.workspace.workspace_task import (
    WorkspaceTask,
    WorkspaceTaskPriority,
    WorkspaceTaskStatus,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.agent.workspace.runtime_role_contract import (
    WORKSPACE_ROLE_LEADER,
    WORKSPACE_ROLE_WORKER,
    WORKSPACE_SESSION_ROLE_KEY,
)

logger = logging.getLogger(__name__)


def _workspace_authority_markers(ctx: ToolContext) -> tuple[str, str] | None:
    runtime_context = ctx.runtime_context or {}
    if runtime_context.get("task_authority") != "workspace":
        return None
    workspace_id = runtime_context.get("workspace_id")
    root_goal_task_id = runtime_context.get("root_goal_task_id")
    if isinstance(workspace_id, str) and isinstance(root_goal_task_id, str):
        return workspace_id, root_goal_task_id
    return None


def _workspace_structural_write_blocked_reason(
    ctx: ToolContext,
    *,
    action: str,
) -> str | None:
    if action not in {"add", "replace"}:
        return None
    runtime_context = ctx.runtime_context or {}
    role = runtime_context.get(WORKSPACE_SESSION_ROLE_KEY)
    if role == WORKSPACE_ROLE_LEADER:
        return None
    has_bound_attempt = bool(runtime_context.get("workspace_task_id")) and bool(
        runtime_context.get("attempt_id")
    )
    if role == WORKSPACE_ROLE_WORKER or has_bound_attempt:
        return (
            "workspace workers cannot create, replace, or dispatch global workspace tasks; "
            "use workspace_report_progress/complete/blocked for the bound task instead"
        )
    return None


def _workspace_priority_from_task(priority: WorkspaceTaskPriority) -> str:
    return {
        WorkspaceTaskPriority.P1: "high",
        WorkspaceTaskPriority.P2: "high",
        WorkspaceTaskPriority.P3: "medium",
        WorkspaceTaskPriority.P4: "low",
        WorkspaceTaskPriority.NONE: "medium",
    }[priority]


def _workspace_status_to_todo(status: WorkspaceTaskStatus) -> str:
    return {
        WorkspaceTaskStatus.TODO: "pending",
        WorkspaceTaskStatus.IN_PROGRESS: "in_progress",
        WorkspaceTaskStatus.DONE: "completed",
        WorkspaceTaskStatus.BLOCKED: "failed",
    }[status]


def _todo_status_to_workspace(status: str | None) -> WorkspaceTaskStatus:
    return {
        "pending": WorkspaceTaskStatus.TODO,
        "in_progress": WorkspaceTaskStatus.IN_PROGRESS,
        "completed": WorkspaceTaskStatus.DONE,
        "failed": WorkspaceTaskStatus.BLOCKED,
        "cancelled": WorkspaceTaskStatus.BLOCKED,
        None: WorkspaceTaskStatus.TODO,
    }[status]


def _todo_status_value(todo: dict[str, Any]) -> str | None:
    raw = todo.get("status")
    if raw is None:
        return None
    normalized = str(raw).strip().lower()
    return normalized or None


def _workspace_todo_requests_cancellation(todo: dict[str, Any]) -> bool:
    return _todo_status_value(todo) == "cancelled"


def _workspace_todo_is_executable_create(todo: dict[str, Any]) -> bool:
    return _todo_status_value(todo) in {None, "pending", "in_progress"}


def _todo_priority_to_workspace(priority: str | None) -> WorkspaceTaskPriority:
    return {
        "high": WorkspaceTaskPriority.P1,
        "medium": WorkspaceTaskPriority.P3,
        "low": WorkspaceTaskPriority.P4,
        None: WorkspaceTaskPriority.NONE,
    }[priority]


def _workspace_task_to_todo(task: WorkspaceTask) -> dict[str, Any]:
    step_id = task.metadata.get("derived_from_internal_plan_step")
    workspace_agent_binding_id = task.get_workspace_agent_binding_id()
    todo: dict[str, Any] = {
        "id": step_id if isinstance(step_id, str) and step_id else task.id,
        "workspace_task_id": task.id,
        "content": task.title,
        "status": _workspace_status_to_todo(task.status),
        "priority": _workspace_priority_from_task(task.priority),
    }
    if workspace_agent_binding_id:
        todo["workspace_agent_id"] = workspace_agent_binding_id
    if task.metadata.get("pending_leader_adjudication") is True:
        todo["pending_leader_adjudication"] = True
    for key in (
        "current_attempt_id",
        "current_attempt_worker_agent_id",
        "last_attempt_id",
        "last_attempt_status",
        "current_attempt_worker_binding_id",
    ):
        value = task.metadata.get(key)
        if isinstance(value, str) and value:
            todo[key] = value
    current_attempt_number = task.metadata.get("current_attempt_number")
    if isinstance(current_attempt_number, int) and current_attempt_number >= 1:
        todo["current_attempt_number"] = current_attempt_number
    for key in (
        "last_worker_report_type",
        "last_worker_report_summary",
        "last_worker_report_id",
        "last_worker_report_fingerprint",
    ):
        value = task.metadata.get(key)
        if isinstance(value, str) and value:
            todo[key] = value
    for key in ("last_worker_report_artifacts", "last_worker_report_verifications"):
        value = task.metadata.get(key)
        if isinstance(value, list):
            todo[key] = [str(item) for item in value if item]
    return todo


# =============================================================================
# TODOREAD TOOL
# =============================================================================


# ---------------------------------------------------------------------------
# @tool_define version of TodoReadTool
# ---------------------------------------------------------------------------

_todoread_session_factory: Callable[..., Any] | None = None


def configure_todoread(
    session_factory: Callable[..., Any],
) -> None:
    """Configure the session factory used by the todoread tool.

    Called at agent startup to inject the DB session factory.
    """
    global _todoread_session_factory
    _todoread_session_factory = session_factory


@tool_define(
    name="todoread",
    description=(
        "Read the task list for the current conversation. "
        "Returns all tasks with their status and priority. "
        "Use this at the start of Build Mode to load the plan, "
        "or to check remaining work after completing tasks."
    ),
    parameters={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "Filter by status",
                "enum": [
                    "pending",
                    "in_progress",
                    "completed",
                    "failed",
                    "cancelled",
                ],
            },
        },
        "required": [],
    },
    permission=None,
    category="task_management",
)
async def todoread_tool(
    ctx: ToolContext,
    *,
    status: str | None = None,
) -> ToolResult:
    """Read the task list for the current conversation."""
    if _todoread_session_factory is None:
        return ToolResult(
            output=json.dumps({"error": "Task storage not configured", "todos": []}),
            is_error=True,
        )

    conversation_id = ctx.conversation_id or ctx.session_id
    workspace_markers = _workspace_authority_markers(ctx)

    async with _todoread_session_factory() as session:
        if workspace_markers is not None:
            from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository import (
                SqlWorkspaceTaskRepository,
            )

            workspace_id, root_goal_task_id = workspace_markers
            tasks = await SqlWorkspaceTaskRepository(session).find_by_root_goal_task_id(
                workspace_id,
                root_goal_task_id,
            )
            todos = [_workspace_task_to_todo(task) for task in tasks]
            if status is not None:
                todos = [todo for todo in todos if todo["status"] == status]
        else:
            from src.infrastructure.adapters.secondary.persistence.sql_agent_task_repository import (
                SqlAgentTaskRepository,
            )

            repo = SqlAgentTaskRepository(session)
            tasks = await repo.find_by_conversation(conversation_id, status=status)
            # Sort: priority (high first), then order_index
            priority_order = {"high": 0, "medium": 1, "low": 2}
            tasks.sort(
                key=lambda t: (
                    priority_order.get(t.priority.value, 1),
                    t.order_index,
                )
            )
            todos = [t.to_dict() for t in tasks]
        await session.commit()

    result = {
        "session_id": ctx.session_id,
        "conversation_id": conversation_id,
        "total_count": len(todos),
        "todos": todos,
    }
    logger.info(
        "todoread: returning %d tasks for %s",
        len(tasks),
        conversation_id,
    )
    return ToolResult(output=json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# @tool_define version of TodoWriteTool
# ---------------------------------------------------------------------------

_todowrite_session_factory: Callable[..., Any] | None = None


def configure_todowrite(
    session_factory: Callable[..., Any],
) -> None:
    """Configure the session factory used by the todowrite tool.

    Called at agent startup to inject the DB session factory.
    """
    global _todowrite_session_factory
    _todowrite_session_factory = session_factory


async def _todowrite_handle_update(
    repo: Any,
    session: Any,
    conversation_id: str,
    todo_id: str | None,
    todos: list[dict[str, Any]],
    ctx: ToolContext,
) -> dict[str, Any]:
    """Handle the 'update' action for a single task."""
    if not todo_id:
        return {"success": False, "error": "todo_id required for update"}

    existing_task = await repo.find_by_id(todo_id)
    if not existing_task or existing_task.conversation_id != conversation_id:
        return {
            "success": False,
            "action": "update",
            "todo_id": todo_id,
            "message": f"Task {todo_id} not found in current conversation",
        }

    updates: dict[str, Any] = {}
    if todos and len(todos) > 0:
        updates = {k: v for k, v in todos[0].items() if k != "id"}
    updated = await repo.update(todo_id, **updates)
    await session.commit()

    if updated:
        await ctx.emit(
            {
                "type": "task_updated",
                "conversation_id": conversation_id,
                "task_id": todo_id,
                "status": updated.status.value,
                "content": updated.content,
            }
        )
        return {
            "success": True,
            "action": "update",
            "todo_id": todo_id,
            "message": f"Updated task {todo_id}",
        }
    return {
        "success": False,
        "action": "update",
        "todo_id": todo_id,
        "message": f"Task {todo_id} not found",
    }


async def _todowrite_replace(
    repo: Any,
    session: Any,
    conversation_id: str,
    todos: list[dict[str, Any]],
    ctx: ToolContext,
) -> dict[str, Any]:
    """Handle the 'replace' action: replace entire task list."""
    task_items = []
    for i, td in enumerate(todos):
        task = AgentTask(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            content=td.get("content", ""),
            status=TaskStatus(td.get("status", "pending")),
            priority=TaskPriority(td.get("priority", "medium")),
            order_index=i,
        )
        if task.validate():
            task_items.append(task)

    await repo.save_all(conversation_id, task_items)
    await session.commit()
    logger.info(
        "[TodoWrite] replace: committed %d tasks for conversation=%s",
        len(task_items),
        conversation_id,
    )

    await ctx.emit(
        {
            "type": "task_list_updated",
            "conversation_id": conversation_id,
            "tasks": [t.to_dict() for t in task_items],
        }
    )
    return {
        "success": True,
        "action": "replace",
        "total_count": len(task_items),
        "message": f"Replaced task list with {len(task_items)} items",
    }


async def _todowrite_add(
    repo: Any,
    session: Any,
    conversation_id: str,
    todos: list[dict[str, Any]],
    ctx: ToolContext,
) -> dict[str, Any]:
    """Handle the 'add' action: append new tasks."""
    existing = await repo.find_by_conversation(conversation_id)
    next_order = max((t.order_index for t in existing), default=-1) + 1
    added = []
    for i, td in enumerate(todos):
        task = AgentTask(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            content=td.get("content", ""),
            status=TaskStatus(td.get("status", "pending")),
            priority=TaskPriority(td.get("priority", "medium")),
            order_index=next_order + i,
        )
        if task.validate():
            await repo.save(task)
            added.append(task)
    await session.commit()

    all_tasks = await repo.find_by_conversation(conversation_id)
    await ctx.emit(
        {
            "type": "task_list_updated",
            "conversation_id": conversation_id,
            "tasks": [t.to_dict() for t in all_tasks],
        }
    )
    return {
        "success": True,
        "action": "add",
        "added_count": len(added),
        "total_count": len(all_tasks),
        "message": f"Added {len(added)} new tasks",
    }


def _workspace_todo_match_key(todo: dict[str, Any]) -> str | None:
    todo_id = todo.get("id")
    if isinstance(todo_id, str) and todo_id:
        return f"id:{todo_id}"
    content = todo.get("content")
    if isinstance(content, str) and content.strip():
        return f"content:{content.strip().lower()}"
    return None


def _workspace_task_match_keys(task: WorkspaceTask) -> tuple[str, ...]:
    keys = [f"id:{task.id}"]
    step_id = task.metadata.get("derived_from_internal_plan_step")
    if isinstance(step_id, str) and step_id and step_id != task.id:
        keys.append(f"id:{step_id}")
    keys.append(f"content:{task.title.strip().lower()}")
    return tuple(keys)


def _workspace_replace_should_create_fresh_task(
    match: WorkspaceTask,
    next_status: WorkspaceTaskStatus | None,
) -> bool:
    return match.status == WorkspaceTaskStatus.BLOCKED and next_status == WorkspaceTaskStatus.TODO


async def _workspace_start_root_for_reactivated_task(
    *,
    command_service: Any,
    task_repo: Any,
    workspace_id: str,
    actor_user_id: str,
    match: WorkspaceTask,
) -> None:
    match_root_goal_task_id = match.metadata.get("root_goal_task_id")
    if not isinstance(match_root_goal_task_id, str) or not match_root_goal_task_id:
        return
    finder = getattr(task_repo, "find_by_id", None)
    if not callable(finder):
        return
    try:
        root_task_result = finder(match_root_goal_task_id)
        root_task = (
            await root_task_result if inspect.isawaitable(root_task_result) else root_task_result
        )
    except Exception:
        root_task = None
    root_status = getattr(root_task, "status", None)
    if root_task is None or root_status != WorkspaceTaskStatus.TODO:
        return
    await command_service.start_task(
        workspace_id=workspace_id,
        task_id=match_root_goal_task_id,
        actor_user_id=actor_user_id,
        actor_type="agent",
        reason="todowrite.workspace_authority.replace.start_root",
        authority=WorkspaceTaskAuthorityContext.leader(None),
    )


async def _workspace_update_matched_replacement(
    *,
    command_service: Any,
    task_repo: Any,
    workspace_id: str,
    actor_user_id: str,
    match: WorkspaceTask,
    todo: dict[str, Any],
    next_status: WorkspaceTaskStatus | None,
    next_priority: WorkspaceTaskPriority | None,
) -> WorkspaceTask:
    title_update = (
        str(todo.get("content"))
        if todo.get("content") is not None and str(todo.get("content")) != match.title
        else None
    )
    status_update = next_status if next_status is not None and next_status != match.status else None
    priority_update = (
        next_priority if next_priority is not None and next_priority != match.priority else None
    )
    if title_update is None and status_update is None and priority_update is None:
        return match

    if status_update == WorkspaceTaskStatus.IN_PROGRESS:
        await _workspace_start_root_for_reactivated_task(
            command_service=command_service,
            task_repo=task_repo,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            match=match,
        )
    return await command_service.update_task(
        workspace_id=workspace_id,
        task_id=match.id,
        actor_user_id=actor_user_id,
        title=title_update,
        status=status_update,
        priority=priority_update,
        actor_type="agent",
        reason="todowrite.workspace_authority.replace",
        authority=WorkspaceTaskAuthorityContext.leader(None),
    )


async def _workspace_todowrite_replace(
    *,
    command_service: Any,
    task_repo: Any,
    workspace_id: str,
    root_goal_task_id: str,
    actor_user_id: str,
    todos: list[dict[str, Any]],
) -> tuple[list[WorkspaceTask], list[WorkspaceTask], list[str]]:
    existing_tasks = await task_repo.find_by_root_goal_task_id(workspace_id, root_goal_task_id)
    existing_by_key = {
        key: task
        for task in existing_tasks
        for key in _workspace_task_match_keys(task)
    }
    matched_keys: set[str] = set()
    updated_tasks: list[WorkspaceTask] = []
    created_tasks: list[WorkspaceTask] = []
    deleted_ids: list[str] = []
    deleted_task_ids: set[str] = set()

    for todo in todos:
        key = _workspace_todo_match_key(todo)
        match = existing_by_key.get(key or "")
        if _workspace_todo_requests_cancellation(todo):
            if match is not None:
                matched_keys.update(_workspace_task_match_keys(match))
                deleted_ids.append(match.id)
                deleted_task_ids.add(match.id)
                await command_service.delete_task(
                    workspace_id=workspace_id,
                    task_id=match.id,
                    actor_user_id=actor_user_id,
                    authority=WorkspaceTaskAuthorityContext.leader(None),
                )
            continue
        next_status = (
            _todo_status_to_workspace(todo.get("status"))
            if todo.get("status") is not None
            else None
        )
        next_priority = (
            _todo_priority_to_workspace(todo.get("priority"))
            if todo.get("priority") is not None
            else None
        )
        if match is not None:
            if _workspace_replace_should_create_fresh_task(match, next_status):
                # A replan replaces blocked work with a fresh execution task.
                # Workspace tasks intentionally do not transition blocked -> todo.
                match = None
            else:
                matched_keys.add(key or "")
                updated_tasks.append(
                    await _workspace_update_matched_replacement(
                        command_service=command_service,
                        task_repo=task_repo,
                        workspace_id=workspace_id,
                        actor_user_id=actor_user_id,
                        match=match,
                        todo=todo,
                        next_status=next_status,
                        next_priority=next_priority,
                    )
                )
                continue

        created = await command_service.create_task(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            title=str(todo.get("content", "")),
            metadata={
                "autonomy_schema_version": 1,
                "task_role": "execution_task",
                "root_goal_task_id": root_goal_task_id,
                "lineage_source": "agent",
                "derived_from_internal_plan_step": todo.get("id"),
            },
            priority=(
                _todo_priority_to_workspace(todo.get("priority"))
                if todo.get("priority") is not None
                else None
            ),
            actor_type="agent",
            reason="todowrite.workspace_authority.replace",
            authority=WorkspaceTaskAuthorityContext.leader(None),
        )
        next_status = (
            _todo_status_to_workspace(todo.get("status"))
            if todo.get("status") is not None
            else None
        )
        if next_status is not None and next_status != WorkspaceTaskStatus.TODO:
            updated = await command_service.update_task(
                workspace_id=workspace_id,
                task_id=created.id,
                actor_user_id=actor_user_id,
                status=next_status,
                actor_type="agent",
                reason="todowrite.workspace_authority.replace.created_status",
                authority=WorkspaceTaskAuthorityContext.leader(None),
            )
            created = updated or created
        created_tasks.append(created)

    for task in existing_tasks:
        if task.id in deleted_task_ids:
            continue
        if any(key in matched_keys for key in _workspace_task_match_keys(task)):
            continue
        deleted_ids.append(task.id)
        await command_service.delete_task(
            workspace_id=workspace_id,
            task_id=task.id,
            actor_user_id=actor_user_id,
            authority=WorkspaceTaskAuthorityContext.leader(None),
        )

    return updated_tasks, created_tasks, deleted_ids


async def _workspace_todowrite_add(
    *,
    command_service: Any,
    task_repo: Any,
    workspace_id: str,
    root_goal_task_id: str,
    actor_user_id: str,
    todos: list[dict[str, Any]],
) -> tuple[list[WorkspaceTask], list[str]]:
    """Create execution tasks under a root goal, de-duplicating by match-key.

    Returns (created_tasks, skipped_titles). Duplicates are identified by
    workspace id, internal plan step id, or content against existing tasks on the root goal.
    """
    existing_tasks = await task_repo.find_by_root_goal_task_id(workspace_id, root_goal_task_id)
    existing_keys = {
        key
        for task in existing_tasks
        for key in _workspace_task_match_keys(task)
    }

    created_tasks: list[WorkspaceTask] = []
    skipped_titles: list[str] = []
    for todo in todos:
        if not _workspace_todo_is_executable_create(todo):
            skipped_titles.append(str(todo.get("content", "")))
            continue
        key = _workspace_todo_match_key(todo)
        if key is not None and key in existing_keys:
            skipped_titles.append(str(todo.get("content", "")))
            continue
        created = await command_service.create_task(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            title=str(todo.get("content", "")),
            metadata={
                "autonomy_schema_version": 1,
                "task_role": "execution_task",
                "root_goal_task_id": root_goal_task_id,
                "lineage_source": "agent",
                "derived_from_internal_plan_step": todo.get("id"),
            },
            priority=(
                _todo_priority_to_workspace(todo.get("priority"))
                if todo.get("priority") is not None
                else None
            ),
            actor_type="agent",
            reason="todowrite.workspace_authority.add",
            authority=WorkspaceTaskAuthorityContext.leader(None),
        )
        created_tasks.append(created)
        if key is not None:
            existing_keys.add(key)
    return created_tasks, skipped_titles


async def _dispatch_created_workspace_tasks(
    *,
    session: Any,
    command_service: Any,
    workspace_id: str,
    created_tasks: list[WorkspaceTask],
    leader_agent_id: str | None,
    actor_user_id: str,
    reason: str,
) -> dict[str, Any]:
    """Route freshly created execution tasks to workers.

    Returns a result dict with ``dispatched`` (bool) and optional
    ``dispatch_skipped_reason`` for observability.
    """
    if not created_tasks:
        return {"dispatched": False, "dispatch_skipped_reason": "no_created_tasks"}
    created_tasks = [
        task
        for task in created_tasks
        if task.status in {WorkspaceTaskStatus.TODO, WorkspaceTaskStatus.IN_PROGRESS}
    ]
    if not created_tasks:
        return {
            "dispatched": False,
            "dispatch_skipped_reason": "no_dispatchable_created_tasks",
        }
    if not leader_agent_id:
        logger.warning(
            "todowrite dispatch skipped: selected_agent_id missing from runtime context",
            extra={
                "workspace_id": workspace_id,
                "created_count": len(created_tasks),
                "reason": reason,
            },
        )
        return {"dispatched": False, "dispatch_skipped_reason": "leader_agent_id_missing"}
    from src.infrastructure.adapters.secondary.persistence.sql_workspace_agent_repository import (
        SqlWorkspaceAgentRepository,
    )
    from src.infrastructure.agent.workspace.dispatcher import (
        assign_execution_tasks_round_robin,
    )

    active_bindings = await SqlWorkspaceAgentRepository(session).find_by_workspace(
        workspace_id,
        active_only=True,
    )
    assigned_count = await assign_execution_tasks_round_robin(
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        created_tasks=created_tasks,
        active_bindings=active_bindings,
        command_service=command_service,
        leader_agent_id=leader_agent_id,
        reason=reason,
    )
    started_count = 0
    start_failed_count = 0
    for task in created_tasks:
        if task.status != WorkspaceTaskStatus.TODO:
            continue
        try:
            await command_service.start_task(
                workspace_id=workspace_id,
                task_id=task.id,
                actor_user_id=actor_user_id,
                actor_type="agent",
                actor_agent_id=leader_agent_id,
                reason=f"{reason}.start",
                authority=WorkspaceTaskAuthorityContext.leader(leader_agent_id),
            )
            started_count += 1
        except Exception:
            start_failed_count += 1
            logger.warning(
                "todowrite dispatch could not start created workspace task",
                exc_info=True,
                extra={
                    "workspace_id": workspace_id,
                    "task_id": task.id,
                    "reason": reason,
                },
            )
    return {
        "dispatched": True,
        "assigned_count": assigned_count,
        "started_count": started_count,
        "start_failed_count": start_failed_count,
    }


@tool_define(
    name="todowrite",
    description=(
        "Write or update the task list for the current conversation. "
        "Actions: 'replace' to set the full task list "
        "(use in Plan Mode to create a work plan), "
        "'add' to append new tasks discovered during execution, "
        "'update' to change a task's status "
        "(pending/in_progress/completed/failed). "
        "Status changes are displayed in the user's UI in real-time."
    ),
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": ("replace (replace entire list), add (append), update (modify one)"),
                "enum": ["replace", "add", "update"],
            },
            "todos": {
                "type": "array",
                "description": ("List of task items (IDs are auto-generated by backend)"),
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Task description",
                        },
                        "status": {
                            "type": "string",
                            "description": ("pending, in_progress, completed, failed, cancelled"),
                        },
                        "priority": {
                            "type": "string",
                            "description": "high, medium, low",
                        },
                    },
                    "required": ["content"],
                },
            },
            "todo_id": {
                "type": "string",
                "description": "For update: the task ID to update",
            },
        },
        "required": ["action"],
    },
    permission=None,
    category="task_management",
)
async def todowrite_tool(  # noqa: C901, PLR0912, PLR0915
    ctx: ToolContext,
    *,
    action: str,
    todos: list[dict[str, Any]] | None = None,
    todo_id: str | None = None,
) -> ToolResult:
    """Write or update the task list for the current conversation."""
    if _todowrite_session_factory is None:
        return ToolResult(
            output=json.dumps({"error": "Task storage not configured"}),
            is_error=True,
        )

    if action not in {"replace", "add", "update"}:
        return ToolResult(
            output=json.dumps({"error": f"Unknown action: {action}"}),
            is_error=True,
        )

    from src.infrastructure.adapters.secondary.persistence.sql_agent_task_repository import (
        SqlAgentTaskRepository,
    )

    conversation_id = ctx.conversation_id or ctx.session_id
    todos_list = todos or []
    result: dict[str, Any] = {}
    workspace_markers = _workspace_authority_markers(ctx)
    structural_write_blocked_reason = (
        _workspace_structural_write_blocked_reason(ctx, action=action)
        if workspace_markers is not None
        else None
    )
    if structural_write_blocked_reason is not None:
        return ToolResult(
            output=json.dumps(
                {
                    "success": False,
                    "action": action,
                    "workspace_scope": "worker",
                    "blocked_reason": structural_write_blocked_reason,
                    "message": structural_write_blocked_reason,
                },
                indent=2,
            )
        )

    async with _todowrite_session_factory() as session:
        if workspace_markers is None:
            repo = SqlAgentTaskRepository(session)

            if action == "replace":
                result = await _todowrite_replace(
                    repo,
                    session,
                    conversation_id,
                    todos_list,
                    ctx,
                )
            elif action == "add":
                result = await _todowrite_add(
                    repo,
                    session,
                    conversation_id,
                    todos_list,
                    ctx,
                )
            elif action == "update":
                result = await _todowrite_handle_update(
                    repo,
                    session,
                    conversation_id,
                    todo_id,
                    todos_list,
                    ctx,
                )
        else:
            from src.application.services.workspace_task_command_service import (
                WorkspaceTaskCommandService,
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

            workspace_id, root_goal_task_id = workspace_markers
            task_repo = SqlWorkspaceTaskRepository(session)
            task_service = WorkspaceTaskService(
                workspace_repo=SqlWorkspaceRepository(session),
                workspace_member_repo=SqlWorkspaceMemberRepository(session),
                workspace_agent_repo=SqlWorkspaceAgentRepository(session),
                workspace_task_repo=task_repo,
            )
            command_service = WorkspaceTaskCommandService(task_service)
            runtime_ctx = ctx.runtime_context or {}
            leader_agent_id_raw = runtime_ctx.get("selected_agent_id")
            leader_agent_id = (
                leader_agent_id_raw if isinstance(leader_agent_id_raw, str) else None
            )
            if action in {"replace", "add"}:
                skipped_titles: list[str] = []
                if action == "replace":
                    updated_tasks, created_tasks, deleted_ids = await _workspace_todowrite_replace(
                        command_service=command_service,
                        task_repo=task_repo,
                        workspace_id=workspace_id,
                        root_goal_task_id=root_goal_task_id,
                        actor_user_id=ctx.user_id,
                        todos=todos_list,
                    )
                    created_count = len(created_tasks)
                    updated_count = len(updated_tasks)
                    deleted_count = len(deleted_ids)
                else:
                    created_tasks, skipped_titles = await _workspace_todowrite_add(
                        command_service=command_service,
                        task_repo=task_repo,
                        workspace_id=workspace_id,
                        root_goal_task_id=root_goal_task_id,
                        actor_user_id=ctx.user_id,
                        todos=todos_list,
                    )
                    created_count = len(created_tasks)
                    updated_count = 0
                    deleted_count = 0
                dispatch_result = await _dispatch_created_workspace_tasks(
                    session=session,
                    command_service=command_service,
                    workspace_id=workspace_id,
                    created_tasks=created_tasks,
                    leader_agent_id=leader_agent_id,
                    actor_user_id=ctx.user_id,
                    reason=f"todowrite.workspace_authority.{action}.dispatch",
                )
                await session.commit()
                try:
                    from src.application.services.workspace_task_event_publisher import (
                        WorkspaceTaskEventPublisher,
                    )
                    from src.infrastructure.agent.state.agent_worker_state import (
                        get_redis_client,
                    )

                    publisher = WorkspaceTaskEventPublisher(await get_redis_client())
                    await publisher.publish_pending_events(command_service.consume_pending_events())
                except Exception:
                    logger.warning(
                        "todowrite.workspace_authority publish_pending_events failed",
                        exc_info=True,
                    )
                try:
                    from src.infrastructure.agent.workspace.worker_launch_drain import (
                        drain_pending_worker_launches_to_outbox,
                    )

                    _ = await drain_pending_worker_launches_to_outbox(command_service, session)
                except Exception:
                    logger.warning(
                        "todowrite.workspace_authority worker_launch_drain failed",
                        exc_info=True,
                    )
                all_tasks = await task_repo.find_by_root_goal_task_id(
                    workspace_id, root_goal_task_id
                )
                await ctx.emit(
                    {
                        "type": "task_list_updated",
                        "conversation_id": conversation_id,
                        "tasks": [_workspace_task_to_todo(task) for task in all_tasks],
                    }
                )
                result = {
                    "success": True,
                    "action": action,
                    "added_count": created_count,
                    "updated_count": updated_count,
                    "deleted_count": deleted_count,
                    "skipped_count": len(skipped_titles),
                    "skipped_titles": skipped_titles,
                    "total_count": len(all_tasks),
                    "dispatched": dispatch_result.get("dispatched", False),
                    "dispatch_started_count": dispatch_result.get("started_count", 0),
                    "dispatch_start_failed_count": dispatch_result.get(
                        "start_failed_count", 0
                    ),
                    "message": (
                        "Workspace-authoritative "
                        f"{action} reconciled tasks "
                        f"(created={created_count}, updated={updated_count}, "
                        f"deleted={deleted_count}, skipped={len(skipped_titles)}, "
                        f"dispatched={dispatch_result.get('dispatched', False)})"
                    ),
                }
                if "dispatch_skipped_reason" in dispatch_result:
                    result["dispatch_skipped_reason"] = dispatch_result["dispatch_skipped_reason"]
            elif action == "update":
                if not todo_id:
                    result = {"success": False, "error": "todo_id required for update"}
                else:
                    existing_task = await task_repo.find_by_id(todo_id)
                    if existing_task is None or existing_task.workspace_id != workspace_id:
                        candidates = await task_repo.find_by_root_goal_task_id(
                            workspace_id,
                            root_goal_task_id,
                        )
                        existing_task = next(
                            (
                                task
                                for task in candidates
                                if f"id:{todo_id}" in _workspace_task_match_keys(task)
                            ),
                            None,
                        )
                    if existing_task is None or existing_task.workspace_id != workspace_id:
                        result = {
                            "success": False,
                            "action": "update",
                            "todo_id": todo_id,
                            "message": f"Task {todo_id} not found in current workspace authority scope",
                        }
                    else:
                        todo_patch = todos_list[0] if todos_list else {}
                        if todo_patch.get("status") == "cancelled":
                            deleted = await command_service.delete_task(
                                workspace_id=workspace_id,
                                task_id=existing_task.id,
                                actor_user_id=ctx.user_id,
                                authority=WorkspaceTaskAuthorityContext.leader(None),
                            )
                            await session.commit()
                            try:
                                from src.application.services.workspace_task_event_publisher import (
                                    WorkspaceTaskEventPublisher,
                                )
                                from src.infrastructure.agent.state.agent_worker_state import (
                                    get_redis_client,
                                )

                                publisher = WorkspaceTaskEventPublisher(
                                    await get_redis_client()
                                )
                                await publisher.publish_pending_events(
                                    command_service.consume_pending_events()
                                )
                            except Exception:
                                logger.warning(
                                    "todowrite.workspace_authority cancel publish failed",
                                    exc_info=True,
                                )
                            all_tasks = await task_repo.find_by_root_goal_task_id(
                                workspace_id,
                                root_goal_task_id,
                            )
                            await ctx.emit(
                                {
                                    "type": "task_list_updated",
                                    "conversation_id": conversation_id,
                                    "tasks": [
                                        _workspace_task_to_todo(task) for task in all_tasks
                                    ],
                                }
                            )
                            result = {
                                "success": deleted,
                                "action": "update",
                                "todo_id": todo_id,
                                "archived": deleted,
                                "message": (
                                    f"Archived workspace task {existing_task.id}"
                                    if deleted
                                    else f"Workspace task {todo_id} could not be archived"
                                ),
                            }
                            logger.info("todowrite: %s completed for %s", action, conversation_id)
                            return ToolResult(output=json.dumps(result, indent=2))
                        next_status = (
                            _todo_status_to_workspace(todo_patch.get("status"))
                            if todo_patch.get("status") is not None
                            else None
                        )
                        next_priority = (
                            _todo_priority_to_workspace(todo_patch.get("priority"))
                            if todo_patch.get("priority") is not None
                            else None
                        )
                        if next_status is not None and (
                            existing_task.metadata.get("pending_leader_adjudication") is True
                            or isinstance(existing_task.metadata.get("current_attempt_id"), str)
                        ):
                            from src.infrastructure.agent.workspace.orchestrator import (
                                WorkspaceAutonomyOrchestrator,
                            )

                            updated = (
                                await WorkspaceAutonomyOrchestrator().adjudicate_worker_report(
                                    workspace_id=workspace_id,
                                    task_id=existing_task.id,
                                    attempt_id=(
                                        existing_task.metadata.get("current_attempt_id")
                                        if isinstance(
                                            existing_task.metadata.get("current_attempt_id"), str
                                        )
                                        else None
                                    ),
                                    actor_user_id=ctx.user_id,
                                    status=next_status,
                                    title=todo_patch.get("content"),
                                    priority=next_priority,
                                )
                            )
                        else:
                            metadata_update: dict[str, object] | None = None
                            if (
                                next_status == WorkspaceTaskStatus.DONE
                                and existing_task.metadata.get("task_role") == "goal_root"
                            ):
                                from src.application.services.workspace_agent_autonomy import (
                                    synthesize_goal_evidence_from_children,
                                )

                                child_tasks = [
                                    task
                                    for task in await task_repo.find_by_root_goal_task_id(
                                        workspace_id, existing_task.id
                                    )
                                    if getattr(task, "archived_at", None) is None
                                ]
                                synthesized = synthesize_goal_evidence_from_children(
                                    root_task=existing_task,
                                    child_tasks=child_tasks,
                                    generated_by_agent_id=leader_agent_id
                                    or ctx.agent_name
                                    or ctx.user_id,
                                )
                                if synthesized is not None:
                                    metadata_update = {"goal_evidence": synthesized}
                            if next_status == WorkspaceTaskStatus.IN_PROGRESS:
                                root_goal_task_id = existing_task.metadata.get("root_goal_task_id")
                                if isinstance(root_goal_task_id, str) and root_goal_task_id:
                                    finder = getattr(task_repo, "find_by_id", None)
                                    if callable(finder):
                                        try:
                                            root_task_result = finder(root_goal_task_id)
                                            root_task = (
                                                await root_task_result
                                                if inspect.isawaitable(root_task_result)
                                                else root_task_result
                                            )
                                        except Exception:
                                            root_task = None
                                        root_status = getattr(root_task, "status", None)
                                        if (
                                            root_task is not None
                                            and root_status == WorkspaceTaskStatus.TODO
                                        ):
                                            await command_service.start_task(
                                                workspace_id=workspace_id,
                                                task_id=root_goal_task_id,
                                                actor_user_id=ctx.user_id,
                                                actor_type="agent",
                                                reason="todowrite.workspace_authority.start_root",
                                                authority=WorkspaceTaskAuthorityContext.leader(
                                                    None
                                                ),
                                            )
                            updated = await command_service.update_task(
                                workspace_id=workspace_id,
                                task_id=existing_task.id,
                                actor_user_id=ctx.user_id,
                                title=todo_patch.get("content"),
                                status=next_status,
                                metadata=metadata_update,
                                priority=next_priority,
                                actor_type="agent",
                                reason="todowrite.workspace_authority",
                                authority=WorkspaceTaskAuthorityContext.leader(None),
                            )
                        if updated is None:
                            result = {
                                "success": False,
                                "action": "update",
                                "todo_id": todo_id,
                                "message": f"Workspace task {todo_id} adjudication failed",
                            }
                        else:
                            await session.commit()
                            await ctx.emit(
                                {
                                    "type": "task_updated",
                                    "conversation_id": conversation_id,
                                    "task_id": todo_id,
                                    "status": _workspace_status_to_todo(updated.status),
                                    "content": updated.title,
                                }
                            )
                            result = {
                                "success": True,
                                "action": "update",
                                "todo_id": todo_id,
                                "message": f"Updated workspace task {todo_id}",
                            }

    logger.info("todowrite: %s completed for %s", action, conversation_id)
    return ToolResult(output=json.dumps(result, indent=2))


# =============================================================================
# TODOWRITE TOOL
# =============================================================================
