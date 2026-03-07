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

from src.domain.model.agent.task import AgentTask, TaskPriority, TaskStatus
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.define import tool_define
from src.infrastructure.agent.tools.result import ToolResult

logger = logging.getLogger(__name__)


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

    from src.infrastructure.adapters.secondary.persistence.sql_agent_task_repository import (
        SqlAgentTaskRepository,
    )

    conversation_id = ctx.conversation_id or ctx.session_id

    async with _todoread_session_factory() as session:
        repo = SqlAgentTaskRepository(session)
        tasks = await repo.find_by_conversation(conversation_id, status=status)
        await session.commit()

    # Sort: priority (high first), then order_index
    priority_order = {"high": 0, "medium": 1, "low": 2}
    tasks.sort(
        key=lambda t: (
            priority_order.get(t.priority.value, 1),
            t.order_index,
        )
    )

    result = {
        "session_id": ctx.session_id,
        "conversation_id": conversation_id,
        "total_count": len(tasks),
        "todos": [t.to_dict() for t in tasks],
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
async def todowrite_tool(
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

    async with _todowrite_session_factory() as session:
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

    logger.info("todowrite: %s completed for %s", action, conversation_id)
    return ToolResult(output=json.dumps(result, indent=2))


# =============================================================================
# TODOWRITE TOOL
# =============================================================================
