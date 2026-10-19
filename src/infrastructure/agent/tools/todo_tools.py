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
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from src.domain.model.agent.task import AgentTask, TaskPriority, TaskStatus
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import ToolInfo, tool_define
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.agent.tools.todo_contract import (
    TODO_UPDATE_INSTRUCTION,
    TODOWRITE_PARAMETERS,
    validate_todowrite_arguments,
)
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


def _todo_optional_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        return datetime.fromisoformat(value)
    return None


def _looks_like_list_position(todo_id: str | None) -> bool:
    return bool(isinstance(todo_id, str) and todo_id.strip().isdigit())


def _todo_id_retry_instruction() -> str:
    return (
        "todo_id must be the exact id returned by todoread in todos[].id "
        "or workspace_task_id. Numeric list positions such as 1 or 2 are invalid. "
        "Call todoread and retry with the copied id."
    )


# =============================================================================
# TODOREAD TOOL
# =============================================================================


# ---------------------------------------------------------------------------
# @tool_define version of TodoReadTool
# ---------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True, slots=True)
class TodoToolRuntime:
    """Persistence dependency captured by one generation's todo tools."""

    session_factory: Callable[..., Any]


_todo_tool_runtime: ContextVar[TodoToolRuntime | None] = ContextVar(
    f"{__name__}.todo_tool_runtime",
    default=None,
)


def _current_todoread_session_factory() -> Callable[..., Any] | None:
    runtime = _todo_tool_runtime.get()
    return runtime.session_factory if runtime is not None else None


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
    permission="read",
    category="task_management",
)
async def todoread_tool(
    ctx: ToolContext,
    *,
    status: str | None = None,
) -> ToolResult:
    """Read the task list for the current conversation."""
    session_factory = _current_todoread_session_factory()
    if session_factory is None:
        return ToolResult(
            output=json.dumps({"error": "Task storage not configured", "todos": []}),
            is_error=True,
        )

    conversation_id = ctx.conversation_id or ctx.session_id
    workspace_markers = _workspace_authority_markers(ctx)

    async with session_factory() as session:
        if workspace_markers is not None:
            from src.infrastructure.workspace_core.legacy_runtime import (
                legacy_workspace_runtime_retired,
            )

            del session, workspace_markers
            legacy_workspace_runtime_retired("todoread Workspace authority")
        else:
            from src.infrastructure.adapters.secondary.persistence.sql_agent_task_repository import (
                SqlAgentTaskRepository,
            )

            repo = SqlAgentTaskRepository(session)
            agent_tasks = await repo.find_by_conversation(conversation_id, status=status)
            # Sort: priority (high first), then order_index
            priority_order = {"high": 0, "medium": 1, "low": 2}
            agent_tasks.sort(
                key=lambda t: (
                    priority_order.get(t.priority.value, 1),
                    t.order_index,
                )
            )
            todos = [t.to_dict() for t in agent_tasks]
        await session.commit()

    result = {
        "session_id": ctx.session_id,
        "conversation_id": conversation_id,
        "total_count": len(todos),
        "update_instruction": (
            "For todowrite action=update, set todo_id to the exact todos[].id value "
            "returned here. Do not use order_index, display order, or list positions."
        ),
        "todos": todos,
    }
    logger.info(
        "todoread: returning %d tasks for %s",
        len(todos),
        conversation_id,
    )
    return ToolResult(output=json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# @tool_define version of TodoWriteTool
# ---------------------------------------------------------------------------


def _current_todowrite_session_factory() -> Callable[..., Any] | None:
    runtime = _todo_tool_runtime.get()
    return runtime.session_factory if runtime is not None else None


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
    if _looks_like_list_position(todo_id):
        return {
            "success": False,
            "action": "update",
            "todo_id": todo_id,
            "error_code": "TODO_ID_IS_LIST_POSITION",
            "message": _todo_id_retry_instruction(),
            "retry_instruction": _todo_id_retry_instruction(),
        }

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
        # Only declared task-edit fields may reach the persistence adapter.
        # In particular, nested input cannot reassign the conversation or ID.
        editable_fields = {
            "content",
            "title",
            "description",
            "estimated_duration_seconds",
            "started_at",
            "completed_at",
            "result_summary",
            "evidence_refs",
            "status",
            "priority",
        }
        updates = {k: v for k, v in todos[0].items() if k in editable_fields}
        for field in ("started_at", "completed_at"):
            if field in updates:
                updates[field] = _todo_optional_datetime(updates[field])
    updated = await repo.update(todo_id, **updates)
    if updated and updates.keys() - _TODO_PROGRESS_FIELDS:
        replacement = await repo.find_by_conversation(conversation_id)
        await repo.save_all(conversation_id, replacement)
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
            title=td.get("title") or td.get("content", ""),
            description=td.get("description"),
            estimated_duration_seconds=td.get("estimated_duration_seconds"),
            started_at=_todo_optional_datetime(td.get("started_at")),
            completed_at=_todo_optional_datetime(td.get("completed_at")),
            result_summary=td.get("result_summary"),
            evidence_refs=[str(value) for value in td.get("evidence_refs", [])],
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
        "todos": [task.to_dict() for task in task_items],
        "update_instruction": (
            "For todowrite action=update, use the exact returned todos[].id as todo_id. "
            "Do not invent IDs or use list positions."
        ),
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
            title=td.get("title") or td.get("content", ""),
            description=td.get("description"),
            estimated_duration_seconds=td.get("estimated_duration_seconds"),
            started_at=_todo_optional_datetime(td.get("started_at")),
            completed_at=_todo_optional_datetime(td.get("completed_at")),
            result_summary=td.get("result_summary"),
            evidence_refs=[str(value) for value in td.get("evidence_refs", [])],
            status=TaskStatus(td.get("status", "pending")),
            priority=TaskPriority(td.get("priority", "medium")),
            order_index=next_order + i,
        )
        if task.validate():
            added.append(task)
    await repo.save_all(conversation_id, [*existing, *added])
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
        "todos": [task.to_dict() for task in all_tasks],
        "update_instruction": (
            "For todowrite action=update, use the exact returned todos[].id as todo_id. "
            "Do not invent IDs or use list positions."
        ),
        "message": f"Added {len(added)} new tasks",
    }


_TODO_PROGRESS_FIELDS = frozenset(
    {"status", "started_at", "completed_at", "result_summary", "evidence_refs"}
)


def _todowrite_permission(arguments: dict[str, Any]) -> str:
    """Declare progress-only effects from the tool's structural argument schema."""
    todo_id = arguments.get("todo_id")
    todos = arguments.get("todos")
    if (
        arguments.get("action") == "update"
        and set(arguments) <= {"action", "todo_id", "todos"}
        and isinstance(todo_id, str)
        and bool(todo_id.strip())
        and isinstance(todos, list)
        and len(todos) == 1
        and isinstance(todos[0], dict)
        and bool(todos[0])
        and set(todos[0]) <= _TODO_PROGRESS_FIELDS
        and validate_todowrite_arguments(arguments) is None
    ):
        return "conversation_progress"
    return "workspace_task_write"


@tool_define(
    name="todowrite",
    description=(
        "Write or update the task list for the current conversation. "
        "Actions: 'replace' to set the full task list "
        "(use in Plan Mode to create a work plan), "
        "'add' to append new tasks discovered during execution, "
        "'update' to change a task's status "
        "(pending/in_progress/completed/failed/cancelled). "
        "Use cancelled for work the user deliberately stops or withdraws; "
        "reserve failed for genuine execution failures and completed for finished work. "
        "After a scoped user stop, inspect task context and cancel only affected remaining work; "
        "preserve genuine failures and continue other independently authorized work. "
        "For update, first call todoread and copy the exact todos[].id into todo_id; "
        "never use list positions such as 1 or 2 as todo_id. "
        "For progress-only updates, send only status, timestamps, result_summary or "
        "evidence_refs in todos[0]; do not resend content, title or priority. "
        "Content is required when adding or replacing tasks. "
        "Status changes are displayed in the user's UI in real-time. " + TODO_UPDATE_INSTRUCTION
    ),
    parameters=TODOWRITE_PARAMETERS,
    permission="workspace_task_write",
    permission_resolver=_todowrite_permission,
    category="task_management",
)
async def todowrite_tool(  # noqa: PLR0911
    ctx: ToolContext,
    *,
    action: str,
    todos: list[dict[str, Any]] | None = None,
    todo_id: str | None = None,
) -> ToolResult:
    """Write or update the task list for the current conversation."""
    invalid = validate_todowrite_arguments({"action": action, "todos": todos, "todo_id": todo_id})
    if invalid is not None:
        return invalid
    session_factory = _current_todowrite_session_factory()
    if session_factory is None:
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
    if action in {"replace", "add"} and any(
        not isinstance(item.get("content"), str) or not item["content"].strip()
        for item in todos_list
    ):
        return ToolResult(
            output=json.dumps(
                {
                    "success": False,
                    "code": "TODO_CONTENT_REQUIRED",
                    "error": "Content is required when adding or replacing tasks.",
                }
            ),
            is_error=True,
        )
    if ctx.runtime_context.get("effective_mode") == "plan" and any(
        item.get("status") in {"in_progress", "completed", "failed"} for item in todos_list
    ):
        return ToolResult(
            output=json.dumps(
                {
                    "success": False,
                    "code": "PLAN_EXECUTION_NOT_APPROVED",
                    "error": "Plan mode cannot record execution progress. Leave execution tasks "
                    "pending and present the plan for approval before Build mode execution.",
                }
            ),
            is_error=True,
        )
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
            ),
            is_error=True,
        )

    async with session_factory() as session:
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
            from src.infrastructure.workspace_core.legacy_runtime import (
                legacy_workspace_runtime_retired,
            )

            legacy_workspace_runtime_retired("todowrite Workspace authority")

    logger.info("todowrite: %s completed for %s", action, conversation_id)
    return ToolResult(output=json.dumps(result, indent=2), is_error=result.get("success") is False)


# =============================================================================
# TODOWRITE TOOL
# =============================================================================


@dataclass(frozen=True, kw_only=True, slots=True)
class _BoundTodoExecutor:
    template: ToolInfo
    runtime: TodoToolRuntime

    async def __call__(self, ctx: ToolContext, **kwargs: Any) -> Any:
        from src.domain.model.plugins.generated_v2 import ScopeKindV2
        from src.infrastructure.plugins.v2.boundary import current_operation_context_v2
        from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

        try:
            operation = current_operation_context_v2()
        except RuntimeV2Error as exc:
            if exc.code != "operation_context_not_pinned":
                raise
        else:
            scope = operation.context.scope
            if (
                scope.kind != ScopeKindV2.SESSION
                or scope.session_id != (ctx.conversation_id or ctx.session_id)
                or (ctx.tenant_id and ctx.tenant_id != scope.tenant_id)
                or (ctx.project_id and ctx.project_id != scope.project_id)
            ):
                raise RuntimeV2Error(
                    "todo_operation_scope_mismatch",
                    "Task tool context must match its active session operation",
                )
        if self.template.name == "todowrite":
            invalid = validate_todowrite_arguments(kwargs)
            if invalid is not None:
                return invalid
        token = _todo_tool_runtime.set(self.runtime)
        try:
            return await self.template.execute(ctx, **kwargs)
        finally:
            _todo_tool_runtime.reset(token)


def make_todo_tools(*, session_factory: Callable[..., Any]) -> dict[str, ToolInfo]:
    """Return todo ToolInfos bound to one generation's persistence dependency."""
    runtime = TodoToolRuntime(session_factory=session_factory)
    return {
        template.name: replace(
            template,
            execute=_BoundTodoExecutor(template=template, runtime=runtime),
        )
        for template in (todoread_tool, todowrite_tool)
    }
