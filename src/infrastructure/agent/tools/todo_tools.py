"""Todo tools for ReAct agent.

Implements todoread and todowrite tools per OpenCode specification.
These tools allow the agent to manage a session-scoped todo list.
"""

import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.infrastructure.agent.tools.base import AgentTool

logger = logging.getLogger(__name__)


# =============================================================================
# TODO DATA MODELS
# =============================================================================


@dataclass
class TodoItem:
    """
    Represents a single todo item.

    Attributes:
        id: Unique identifier for the todo item
        content: Brief description of the task
        status: Current status (pending, in_progress, completed, cancelled)
        priority: Priority level (high, medium, low)
        created_at: Timestamp when the todo was created
        updated_at: Timestamp when the todo was last updated
    """

    id: str
    content: str
    status: str = "pending"  # pending, in_progress, completed, cancelled
    priority: str = "medium"  # high, medium, low
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        """Set timestamps if not provided."""
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TodoItem":
        """Create from dictionary."""
        return cls(**data)

    def validate(self) -> bool:
        """Validate todo item data."""
        valid_statuses = {"pending", "in_progress", "completed", "cancelled"}
        valid_priorities = {"high", "medium", "low"}

        if not self.content or not self.content.strip():
            return False
        if self.status not in valid_statuses:
            return False
        if self.priority not in valid_priorities:
            return False
        return True


# =============================================================================
# TODO STORAGE
# =============================================================================


class TodoStorage:
    """
    In-memory storage for session-scoped todo lists.

    This is a simple in-memory implementation that stores todos
    per session. In production, this could be backed by Redis
    or a database.
    """

    def __init__(self):
        """Initialize empty storage."""
        self._storage: Dict[str, List[TodoItem]] = {}

    def get(self, session_id: str) -> List[TodoItem]:
        """
        Get all todos for a session.

        Args:
            session_id: The session identifier

        Returns:
            List of TodoItem objects (empty list if none found)
        """
        return self._storage.get(session_id, []).copy()

    def set(self, session_id: str, todos: List[TodoItem]) -> None:
        """
        Set todos for a session (replaces existing).

        Args:
            session_id: The session identifier
            todos: List of TodoItem objects to store
        """
        # Validate all todos before storing
        valid_todos = [t for t in todos if t.validate()]
        self._storage[session_id] = valid_todos
        logger.debug(f"Stored {len(valid_todos)} todos for session {session_id}")

    def add(self, session_id: str, todo: TodoItem) -> None:
        """
        Add a single todo to a session.

        Args:
            session_id: The session identifier
            todo: TodoItem to add
        """
        if not todo.validate():
            logger.warning(f"Invalid todo item, skipping: {todo}")
            return

        if session_id not in self._storage:
            self._storage[session_id] = []

        self._storage[session_id].append(todo)
        logger.debug(f"Added todo {todo.id} to session {session_id}")

    def update(self, session_id: str, todo_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update a specific todo in a session.

        Args:
            session_id: The session identifier
            todo_id: The ID of the todo to update
            updates: Dictionary of fields to update

        Returns:
            True if updated, False if not found
        """
        if session_id not in self._storage:
            return False

        for i, todo in enumerate(self._storage[session_id]):
            if todo.id == todo_id:
                # Update fields
                for key, value in updates.items():
                    if hasattr(todo, key):
                        setattr(todo, key, value)
                        # Update timestamp
                        if key != "updated_at":
                            todo.updated_at = datetime.now().isoformat()
                return True

        return False

    def delete(self, session_id: str, todo_id: str) -> bool:
        """
        Delete a specific todo from a session.

        Args:
            session_id: The session identifier
            todo_id: The ID of the todo to delete

        Returns:
            True if deleted, False if not found
        """
        if session_id not in self._storage:
            return False

        for i, todo in enumerate(self._storage[session_id]):
            if todo.id == todo_id:
                del self._storage[session_id][i]
                return True

        return False

    def clear(self, session_id: str) -> None:
        """
        Clear all todos for a session.

        Args:
            session_id: The session identifier
        """
        if session_id in self._storage:
            del self._storage[session_id]
            logger.debug(f"Cleared todos for session {session_id}")


# Global storage instance
_todo_storage = TodoStorage()


def get_todo_storage() -> TodoStorage:
    """Get the global todo storage instance."""
    return _todo_storage


# =============================================================================
# TODOREAD TOOL
# =============================================================================


class TodoReadTool(AgentTool):
    """
    Tool for reading the todo list for a session.

    Returns all todos in the current session, optionally filtered
    by status or priority.
    """

    def __init__(self):
        """Initialize the todoread tool."""
        super().__init__(
            name="todoread",
            description="Read the todo list for the current session. Returns all pending and active tasks.",
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get the parameters schema for LLM function calling."""
        return {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The session identifier (conversation ID)",
                },
                "status": {
                    "type": "string",
                    "description": "Optional: Filter by status (pending, in_progress, completed, cancelled)",
                    "enum": ["pending", "in_progress", "completed", "cancelled"],
                },
                "priority": {
                    "type": "string",
                    "description": "Optional: Filter by priority (high, medium, low)",
                    "enum": ["high", "medium", "low"],
                },
            },
            "required": ["session_id"],
        }

    def validate_args(self, **kwargs: Any) -> bool:
        """Validate tool arguments."""
        session_id = kwargs.get("session_id")
        if not session_id or not isinstance(session_id, str):
            return False

        status = kwargs.get("status")
        if status and status not in {"pending", "in_progress", "completed", "cancelled"}:
            return False

        priority = kwargs.get("priority")
        if priority and priority not in {"high", "medium", "low"}:
            return False

        return True

    async def execute(self, session_id: str, status: Optional[str] = None, priority: Optional[str] = None, **kwargs: Any) -> str:
        """
        Execute the todoread tool.

        Args:
            session_id: The session identifier
            status: Optional status filter
            priority: Optional priority filter
            **kwargs: Additional arguments

        Returns:
            JSON string containing the todo list
        """
        storage = get_todo_storage()
        todos = storage.get(session_id)

        # Apply filters
        if status:
            todos = [t for t in todos if t.status == status]
        if priority:
            todos = [t for t in todos if t.priority == priority]

        # Sort by priority (high first) and then by created_at
        priority_order = {"high": 0, "medium": 1, "low": 2}
        todos.sort(key=lambda t: (priority_order.get(t.priority, 1), t.created_at))

        # Convert to dict for JSON serialization
        result = {
            "session_id": session_id,
            "total_count": len(todos),
            "todos": [t.to_dict() for t in todos],
        }

        logger.info(f"todoread: returning {len(todos)} todos for session {session_id}")
        return json.dumps(result, indent=2)


# =============================================================================
# TODOWRITE TOOL
# =============================================================================


class TodoWriteTool(AgentTool):
    """
    Tool for writing/updating the todo list for a session.

    Can replace the entire list, add new todos, or update existing todos.
    """

    def __init__(self):
        """Initialize the todowrite tool."""
        super().__init__(
            name="todowrite",
            description="Write or update the todo list for the current session. Use this to add, update, or organize tasks.",
        )

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get the parameters schema for LLM function calling."""
        return {
            "type": "object",
            "properties": {
                "session_id": {
                    "type": "string",
                    "description": "The session identifier (conversation ID)",
                },
                "action": {
                    "type": "string",
                    "description": "Action to perform: replace (replace entire list), add (add new todos), update (update existing todo)",
                    "enum": ["replace", "add", "update"],
                },
                "todos": {
                    "type": "array",
                    "description": "List of todo items (each with content, status, priority)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "id": {"type": "string", "description": "Todo ID (required for update, optional for add)"},
                            "content": {"type": "string", "description": "Task description"},
                            "status": {"type": "string", "description": "Status: pending, in_progress, completed, cancelled"},
                            "priority": {"type": "string", "description": "Priority: high, medium, low"},
                        },
                        "required": ["content"],
                    },
                },
                "todo_id": {
                    "type": "string",
                    "description": "For update action: the ID of the todo to update",
                },
            },
            "required": ["session_id", "action"],
        }

    def validate_args(self, **kwargs: Any) -> bool:
        """Validate tool arguments."""
        session_id = kwargs.get("session_id")
        if not session_id or not isinstance(session_id, str):
            return False

        action = kwargs.get("action")
        if action not in {"replace", "add", "update"}:
            return False

        if action == "update":
            todo_id = kwargs.get("todo_id")
            if not todo_id:
                return False

        return True

    async def execute(
        self,
        session_id: str,
        action: str,
        todos: Optional[List[Dict[str, Any]]] = None,
        todo_id: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        """
        Execute the todowrite tool.

        Args:
            session_id: The session identifier
            action: Action to perform (replace, add, update)
            todos: List of todo items (for replace and add actions)
            todo_id: ID of todo to update (for update action)
            **kwargs: Additional arguments

        Returns:
            JSON string containing the result
        """
        storage = get_todo_storage()
        todos = todos or []

        if action == "replace":
            # Replace entire todo list
            todo_items = []
            for todo_data in todos:
                # Generate ID if not provided
                if "id" not in todo_data:
                    todo_data["id"] = str(uuid.uuid4())
                todo_items.append(TodoItem.from_dict(todo_data))

            storage.set(session_id, todo_items)
            result = {
                "success": True,
                "action": "replace",
                "session_id": session_id,
                "total_count": len(todo_items),
                "message": f"Replaced todo list with {len(todo_items)} items",
            }

        elif action == "add":
            # Add new todos to existing list
            added_count = 0
            for todo_data in todos:
                # Generate ID if not provided
                if "id" not in todo_data:
                    todo_data["id"] = str(uuid.uuid4())
                todo_item = TodoItem.from_dict(todo_data)
                if todo_item.validate():
                    storage.add(session_id, todo_item)
                    added_count += 1

            result = {
                "success": True,
                "action": "add",
                "session_id": session_id,
                "added_count": added_count,
                "total_count": len(storage.get(session_id)),
                "message": f"Added {added_count} new todos",
            }

        elif action == "update":
            # Update a specific todo
            if not todo_id:
                result = {
                    "success": False,
                    "action": "update",
                    "error": "todo_id is required for update action",
                }
            else:
                # Extract updates from first todo in list
                updates = {}
                if todos and len(todos) > 0:
                    updates = {k: v for k, v in todos[0].items() if k != "id"}

                success = storage.update(session_id, todo_id, updates)
                result = {
                    "success": success,
                    "action": "update",
                    "session_id": session_id,
                    "todo_id": todo_id,
                    "message": f"Updated todo {todo_id}" if success else f"Todo {todo_id} not found",
                }

        logger.info(f"todowrite: {action} action completed for session {session_id}")
        return json.dumps(result, indent=2)


# =============================================================================
# TOOL FACTORIES
# =============================================================================


def create_todoread_tool() -> TodoReadTool:
    """Create a todoread tool instance."""
    return TodoReadTool()


def create_todowrite_tool() -> TodoWriteTool:
    """Create a todowrite tool instance."""
    return TodoWriteTool()
