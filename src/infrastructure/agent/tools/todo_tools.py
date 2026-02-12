"""Todo tools for ReAct agent.

DB-persistent task management. The agent uses todoread/todowrite to create,
update, and track a task checklist per conversation. Tasks are stored in
PostgreSQL and streamed to the frontend via SSE events.
"""

import json
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

from src.domain.model.agent.task import AgentTask, TaskPriority, TaskStatus
from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)


# =============================================================================
# TODOREAD TOOL
# =============================================================================


class TodoReadTool(AgentTool):
    """Read the task list for a conversation from DB."""

    def __init__(self, session_factory: Optional[Callable] = None):
        super().__init__(
            name="todoread",
            description=(
                "Read the task list for the current conversation. "
                "Returns all tasks with their status and priority. "
                "Use this at the start of Build Mode to load the plan, "
                "or to check remaining work after completing tasks."
            ),
        )
        self._session_factory = session_factory

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status",
                    "enum": ["pending", "in_progress", "completed", "failed", "cancelled"],
                },
            },
            "required": [],
        }

    def validate_args(self, **kwargs: Any) -> bool:
        status = kwargs.get("status")
        valid = {"pending", "in_progress", "completed", "failed", "cancelled"}
        if status and status not in valid:
            return False
        return True

    async def execute(
        self,
        session_id: str,
        status: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        if not self._session_factory:
            return json.dumps({"error": "Task storage not configured", "todos": []})

        from src.infrastructure.adapters.secondary.persistence.sql_agent_task_repository import (
            SqlAgentTaskRepository,
        )

        async with self._session_factory() as session:
            repo = SqlAgentTaskRepository(session)
            tasks = await repo.find_by_conversation(session_id, status=status)
            await session.commit()

        # Sort: priority (high first), then order_index
        priority_order = {"high": 0, "medium": 1, "low": 2}
        tasks.sort(key=lambda t: (priority_order.get(t.priority.value, 1), t.order_index))

        result = {
            "session_id": session_id,
            "total_count": len(tasks),
            "todos": [t.to_dict() for t in tasks],
        }
        logger.info(f"todoread: returning {len(tasks)} tasks for {session_id}")
        return json.dumps(result, indent=2)


# =============================================================================
# TODOWRITE TOOL
# =============================================================================


class TodoWriteTool(AgentTool):
    """Write/update the task list for a conversation. Persists to DB."""

    def __init__(self, session_factory: Optional[Callable] = None):
        super().__init__(
            name="todowrite",
            description=(
                "Write or update the task list for the current conversation. "
                "Actions: 'replace' to set the full task list (use in Plan Mode to create a work plan), "
                "'add' to append new tasks discovered during execution, "
                "'update' to change a task's status (pending/in_progress/completed/failed). "
                "Status changes are displayed in the user's UI in real-time."
            ),
        )
        self._session_factory = session_factory
        self._pending_events: List[Dict[str, Any]] = []

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "replace (replace entire list), add (append), update (modify one)",
                    "enum": ["replace", "add", "update"],
                },
                "todos": {
                    "type": "array",
                    "description": "List of task items",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Task ID (for update)"},
                            "content": {"type": "string", "description": "Task description"},
                            "status": {
                                "type": "string",
                                "description": "pending, in_progress, completed, failed, cancelled",
                            },
                            "priority": {"type": "string", "description": "high, medium, low"},
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
        }

    def validate_args(self, **kwargs: Any) -> bool:
        action = kwargs.get("action")
        if action not in {"replace", "add", "update"}:
            return False
        if action == "update" and not kwargs.get("todo_id"):
            return False
        return True

    def consume_pending_events(self) -> List[Dict[str, Any]]:
        """Consume and return any pending SSE events from the last execute()."""
        events = list(self._pending_events)
        self._pending_events.clear()
        return events

    async def execute(
        self,
        session_id: str,
        action: str,
        todos: Optional[List[Dict[str, Any]]] = None,
        todo_id: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        self._pending_events.clear()

        if not self._session_factory:
            return json.dumps({"error": "Task storage not configured"})

        from src.infrastructure.adapters.secondary.persistence.sql_agent_task_repository import (
            SqlAgentTaskRepository,
        )

        todos = todos or []
        result: Dict[str, Any] = {}

        async with self._session_factory() as session:
            repo = SqlAgentTaskRepository(session)

            if action == "replace":
                task_items = []
                for i, td in enumerate(todos):
                    task = AgentTask(
                        id=td.get("id", str(uuid.uuid4())),
                        conversation_id=session_id,
                        content=td.get("content", ""),
                        status=TaskStatus(td.get("status", "pending")),
                        priority=TaskPriority(td.get("priority", "medium")),
                        order_index=i,
                    )
                    if task.validate():
                        task_items.append(task)

                await repo.save_all(session_id, task_items)
                await session.commit()
                logger.info(
                    f"[TodoWrite] replace: committed {len(task_items)} tasks "
                    f"for conversation={session_id}"
                )

                self._pending_events.append(
                    {
                        "type": "task_list_updated",
                        "conversation_id": session_id,
                        "tasks": [t.to_dict() for t in task_items],
                    }
                )
                result = {
                    "success": True,
                    "action": "replace",
                    "total_count": len(task_items),
                    "message": f"Replaced task list with {len(task_items)} items",
                }

            elif action == "add":
                existing = await repo.find_by_conversation(session_id)
                next_order = max((t.order_index for t in existing), default=-1) + 1
                added = []
                for i, td in enumerate(todos):
                    task = AgentTask(
                        id=td.get("id", str(uuid.uuid4())),
                        conversation_id=session_id,
                        content=td.get("content", ""),
                        status=TaskStatus(td.get("status", "pending")),
                        priority=TaskPriority(td.get("priority", "medium")),
                        order_index=next_order + i,
                    )
                    if task.validate():
                        await repo.save(task)
                        added.append(task)
                await session.commit()

                all_tasks = await repo.find_by_conversation(session_id)
                self._pending_events.append(
                    {
                        "type": "task_list_updated",
                        "conversation_id": session_id,
                        "tasks": [t.to_dict() for t in all_tasks],
                    }
                )
                result = {
                    "success": True,
                    "action": "add",
                    "added_count": len(added),
                    "total_count": len(all_tasks),
                    "message": f"Added {len(added)} new tasks",
                }

            elif action == "update":
                if not todo_id:
                    result = {"success": False, "error": "todo_id required for update"}
                else:
                    updates = {}
                    if todos and len(todos) > 0:
                        updates = {k: v for k, v in todos[0].items() if k != "id"}
                    updated = await repo.update(todo_id, **updates)
                    await session.commit()

                    if updated:
                        self._pending_events.append(
                            {
                                "type": "task_updated",
                                "conversation_id": session_id,
                                "task_id": todo_id,
                                "status": updated.status.value,
                                "content": updated.content,
                            }
                        )
                        result = {
                            "success": True,
                            "action": "update",
                            "todo_id": todo_id,
                            "message": f"Updated task {todo_id}",
                        }
                    else:
                        result = {
                            "success": False,
                            "action": "update",
                            "todo_id": todo_id,
                            "message": f"Task {todo_id} not found",
                        }

        logger.info(f"todowrite: {action} completed for {session_id}")
        return json.dumps(result, indent=2)


# =============================================================================
# TOOL FACTORIES
# =============================================================================


def create_todoread_tool(session_factory: Optional[Callable] = None) -> TodoReadTool:
    """Create a TodoReadTool instance."""
    return TodoReadTool(session_factory=session_factory)


def create_todowrite_tool(session_factory: Optional[Callable] = None) -> TodoWriteTool:
    """Create a TodoWriteTool instance."""
    return TodoWriteTool(session_factory=session_factory)
