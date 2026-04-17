"""Todo tools for ReAct agent.

DB-persistent task management. The agent uses todoread/todowrite to create,
update, and track a task checklist per conversation. Tasks are stored in
PostgreSQL and streamed to the frontend via SSE events.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from typing import Any

from src.application.services.workspace_task_service import WorkspaceTaskService
from src.domain.model.agent.task import AgentTask, TaskPriority, TaskStatus
from src.domain.model.workspace.workspace_task import (
    WorkspaceTask,
    WorkspaceTaskPriority,
    WorkspaceTaskStatus,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

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


def _todo_priority_to_workspace(priority: str | None) -> WorkspaceTaskPriority:
    return {
        "high": WorkspaceTaskPriority.P1,
        "medium": WorkspaceTaskPriority.P3,
        "low": WorkspaceTaskPriority.P4,
        None: WorkspaceTaskPriority.NONE,
    }[priority]


def _workspace_task_to_todo(task: WorkspaceTask) -> dict[str, Any]:
    step_id = task.metadata.get("derived_from_internal_plan_step")
    todo: dict[str, Any] = {
        "id": step_id if isinstance(step_id, str) and step_id else task.id,
        "workspace_task_id": task.id,
        "content": task.title,
        "status": _workspace_status_to_todo(task.status),
        "priority": _workspace_priority_from_task(task.priority),
    }
    if task.metadata.get("pending_leader_adjudication") is True:
        todo["pending_leader_adjudication"] = True
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


def _workspace_task_match_key(task: WorkspaceTask) -> str:
    step_id = task.metadata.get("derived_from_internal_plan_step")
    if isinstance(step_id, str) and step_id:
        return f"id:{step_id}"
    return f"content:{task.title.strip().lower()}"


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
    existing_by_key = {_workspace_task_match_key(task): task for task in existing_tasks}
    matched_keys: set[str] = set()
    updated_tasks: list[WorkspaceTask] = []
    created_tasks: list[WorkspaceTask] = []

    for todo in todos:
        key = _workspace_todo_match_key(todo)
        match = existing_by_key.get(key or "")
        if match is not None:
            matched_keys.add(key or "")
            updated_tasks.append(
                await command_service.update_task(
                    workspace_id=workspace_id,
                    task_id=match.id,
                    actor_user_id=actor_user_id,
                    title=todo.get("content"),
                    status=(
                        _todo_status_to_workspace(todo.get("status"))
                        if todo.get("status") is not None
                        else None
                    ),
                    priority=(
                        _todo_priority_to_workspace(todo.get("priority"))
                        if todo.get("priority") is not None
                        else None
                    ),
                    actor_type="agent",
                    reason="todowrite.workspace_authority.replace",
                )
            )
            continue

        created_tasks.append(
            await command_service.create_task(
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
            )
        )

    deleted_ids: list[str] = []
    for task in existing_tasks:
        if _workspace_task_match_key(task) in matched_keys:
            continue
        deleted_ids.append(task.id)
        await command_service.delete_task(
            workspace_id=workspace_id,
            task_id=task.id,
            actor_user_id=actor_user_id,
        )

    return updated_tasks, created_tasks, deleted_ids


async def _workspace_todowrite_add(
    *,
    command_service: Any,
    workspace_id: str,
    root_goal_task_id: str,
    actor_user_id: str,
    todos: list[dict[str, Any]],
) -> list[WorkspaceTask]:
    created_tasks: list[WorkspaceTask] = []
    for todo in todos:
        created_tasks.append(
            await command_service.create_task(
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
            )
        )
    return created_tasks


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
            if action in {"replace", "add"}:
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
                    created_tasks = await _workspace_todowrite_add(
                        command_service=command_service,
                        workspace_id=workspace_id,
                        root_goal_task_id=root_goal_task_id,
                        actor_user_id=ctx.user_id,
                        todos=todos_list,
                    )
                    created_count = len(created_tasks)
                    updated_count = 0
                    deleted_count = 0
                await session.commit()
                all_tasks = await task_repo.find_by_root_goal_task_id(workspace_id, root_goal_task_id)
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
                    "total_count": len(all_tasks),
                    "message": (
                        "Workspace-authoritative "
                        f"{action} reconciled tasks "
                        f"(created={created_count}, updated={updated_count}, deleted={deleted_count})"
                    ),
                }
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
                                if _workspace_task_match_key(task) == f"id:{todo_id}"
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
                        if (
                            next_status is not None
                            and existing_task.metadata.get("pending_leader_adjudication") is True
                        ):
                            from src.infrastructure.agent.workspace.workspace_goal_runtime import (
                                adjudicate_workspace_worker_report,
                            )

                            updated = await adjudicate_workspace_worker_report(
                                workspace_id=workspace_id,
                                task_id=existing_task.id,
                                actor_user_id=ctx.user_id,
                                status=next_status,
                                title=todo_patch.get("content"),
                                priority=next_priority,
                            )
                        else:
                            updated = await command_service.update_task(
                                workspace_id=workspace_id,
                                task_id=existing_task.id,
                                actor_user_id=ctx.user_id,
                                title=todo_patch.get("content"),
                                status=next_status,
                                priority=next_priority,
                                actor_type="agent",
                                reason="todowrite.workspace_authority",
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
