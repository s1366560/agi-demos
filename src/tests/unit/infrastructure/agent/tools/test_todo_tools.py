"""Tests for todo tools using TDD methodology.

Tests for todoread and todowrite tools following OpenCode specification.
"""

import json

import pytest

from src.infrastructure.agent.tools.todo_tools import (
    TodoItem,
    TodoReadTool,
    TodoStorage,
    TodoWriteTool,
)


class TestTodoItem:
    """Test suite for TodoItem dataclass."""

    def test_create_todo_item(self):
        """Test creating a todo item with minimal fields."""
        todo = TodoItem(id="1", content="Test task")
        assert todo.id == "1"
        assert todo.content == "Test task"
        assert todo.status == "pending"
        assert todo.priority == "medium"

    def test_create_todo_item_with_all_fields(self):
        """Test creating a todo item with all fields."""
        todo = TodoItem(
            id="1",
            content="Test task",
            status="in_progress",
            priority="high",
        )
        assert todo.status == "in_progress"
        assert todo.priority == "high"

    def test_todo_item_to_dict(self):
        """Test converting todo item to dictionary."""
        todo = TodoItem(id="1", content="Test task")
        data = todo.to_dict()
        assert data["id"] == "1"
        assert data["content"] == "Test task"
        assert data["status"] == "pending"

    def test_todo_item_from_dict(self):
        """Test creating todo item from dictionary."""
        data = {
            "id": "1",
            "content": "Test task",
            "status": "completed",
            "priority": "low",
        }
        todo = TodoItem.from_dict(data)
        assert todo.id == "1"
        assert todo.status == "completed"
        assert todo.priority == "low"

    def test_todo_item_validation_valid(self):
        """Test validation of valid todo item."""
        todo = TodoItem(id="1", content="Test task")
        assert todo.validate() is True

    def test_todo_item_validation_empty_content(self):
        """Test validation fails with empty content."""
        todo = TodoItem(id="1", content="")
        assert todo.validate() is False

    def test_todo_item_validation_invalid_status(self):
        """Test validation fails with invalid status."""
        todo = TodoItem(id="1", content="Test task", status="invalid")
        assert todo.validate() is False

    def test_todo_item_validation_invalid_priority(self):
        """Test validation fails with invalid priority."""
        todo = TodoItem(id="1", content="Test task", priority="invalid")
        assert todo.validate() is False


class TestTodoStorage:
    """Test suite for TodoStorage."""

    def test_get_empty_session(self):
        """Test getting todos from empty session."""
        storage = TodoStorage()
        todos = storage.get("session-1")
        assert todos == []

    def test_set_and_get_todos(self):
        """Test setting and getting todos."""
        storage = TodoStorage()
        todos = [
            TodoItem(id="1", content="Task 1"),
            TodoItem(id="2", content="Task 2"),
        ]
        storage.set("session-1", todos)

        retrieved = storage.get("session-1")
        assert len(retrieved) == 2
        assert retrieved[0].content == "Task 1"
        assert retrieved[1].content == "Task 2"

    def test_add_todo(self):
        """Test adding a single todo."""
        storage = TodoStorage()
        todo = TodoItem(id="1", content="New task")
        storage.add("session-1", todo)

        retrieved = storage.get("session-1")
        assert len(retrieved) == 1
        assert retrieved[0].content == "New task"

    def test_update_todo(self):
        """Test updating a todo."""
        storage = TodoStorage()
        todo = TodoItem(id="1", content="Original", status="pending")
        storage.add("session-1", todo)

        success = storage.update("session-1", "1", {"status": "completed"})
        assert success is True

        retrieved = storage.get("session-1")
        assert retrieved[0].status == "completed"

    def test_update_nonexistent_todo(self):
        """Test updating a todo that doesn't exist."""
        storage = TodoStorage()
        success = storage.update("session-1", "999", {"status": "completed"})
        assert success is False

    def test_delete_todo(self):
        """Test deleting a todo."""
        storage = TodoStorage()
        todo = TodoItem(id="1", content="To delete")
        storage.add("session-1", todo)

        success = storage.delete("session-1", "1")
        assert success is True

        retrieved = storage.get("session-1")
        assert len(retrieved) == 0

    def test_delete_nonexistent_todo(self):
        """Test deleting a todo that doesn't exist."""
        storage = TodoStorage()
        success = storage.delete("session-1", "999")
        assert success is False

    def test_clear_session(self):
        """Test clearing all todos for a session."""
        storage = TodoStorage()
        storage.add("session-1", TodoItem(id="1", content="Task 1"))
        storage.add("session-1", TodoItem(id="2", content="Task 2"))

        storage.clear("session-1")

        retrieved = storage.get("session-1")
        assert len(retrieved) == 0

    def test_isolated_sessions(self):
        """Test that sessions are isolated from each other."""
        storage = TodoStorage()
        storage.add("session-1", TodoItem(id="1", content="Session 1 task"))
        storage.add("session-2", TodoItem(id="2", content="Session 2 task"))

        session1_todos = storage.get("session-1")
        session2_todos = storage.get("session-2")

        assert len(session1_todos) == 1
        assert len(session2_todos) == 1
        assert session1_todos[0].content == "Session 1 task"
        assert session2_todos[0].content == "Session 2 task"


class TestTodoReadTool:
    """Test suite for TodoReadTool."""

    @pytest.fixture
    def tool(self):
        """Provide a TodoReadTool instance."""
        return TodoReadTool()

    @pytest.fixture
    def storage(self):
        """Provide a fresh TodoStorage instance."""
        return TodoStorage()

    @pytest.mark.asyncio
    async def test_read_empty_session(self, tool, storage, monkeypatch):
        """Test reading todos from an empty session."""
        # Use our fresh storage
        monkeypatch.setattr("src.infrastructure.agent.tools.todo_tools._todo_storage", storage)

        result = await tool.execute(session_id="empty-session")
        data = json.loads(result)

        assert data["session_id"] == "empty-session"
        assert data["total_count"] == 0
        assert data["todos"] == []

    @pytest.mark.asyncio
    async def test_read_with_todos(self, tool, storage, monkeypatch):
        """Test reading todos from a session with todos."""
        storage.add("session-1", TodoItem(id="1", content="Task 1"))
        storage.add("session-1", TodoItem(id="2", content="Task 2"))
        monkeypatch.setattr("src.infrastructure.agent.tools.todo_tools._todo_storage", storage)

        result = await tool.execute(session_id="session-1")
        data = json.loads(result)

        assert data["total_count"] == 2
        assert len(data["todos"]) == 2
        assert data["todos"][0]["content"] == "Task 1"

    @pytest.mark.asyncio
    async def test_read_with_status_filter(self, tool, storage, monkeypatch):
        """Test reading todos filtered by status."""
        storage.add("session-1", TodoItem(id="1", content="Task 1", status="pending"))
        storage.add("session-1", TodoItem(id="2", content="Task 2", status="completed"))
        monkeypatch.setattr("src.infrastructure.agent.tools.todo_tools._todo_storage", storage)

        result = await tool.execute(session_id="session-1", status="pending")
        data = json.loads(result)

        assert data["total_count"] == 1
        assert data["todos"][0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_read_with_priority_filter(self, tool, storage, monkeypatch):
        """Test reading todos filtered by priority."""
        storage.add("session-1", TodoItem(id="1", content="Task 1", priority="high"))
        storage.add("session-1", TodoItem(id="2", content="Task 2", priority="low"))
        monkeypatch.setattr("src.infrastructure.agent.tools.todo_tools._todo_storage", storage)

        result = await tool.execute(session_id="session-1", priority="high")
        data = json.loads(result)

        assert data["total_count"] == 1
        assert data["todos"][0]["priority"] == "high"

    @pytest.mark.asyncio
    async def test_read_sorting_by_priority(self, tool, storage, monkeypatch):
        """Test that todos are sorted by priority."""
        storage.add("session-1", TodoItem(id="1", content="Low", priority="low"))
        storage.add("session-1", TodoItem(id="2", content="High", priority="high"))
        storage.add("session-1", TodoItem(id="3", content="Medium", priority="medium"))
        monkeypatch.setattr("src.infrastructure.agent.tools.todo_tools._todo_storage", storage)

        result = await tool.execute(session_id="session-1")
        data = json.loads(result)

        # Should be sorted: high, medium, low
        assert data["todos"][0]["priority"] == "high"
        assert data["todos"][1]["priority"] == "medium"
        assert data["todos"][2]["priority"] == "low"

    def test_validate_args_valid(self, tool):
        """Test argument validation with valid args."""
        assert tool.validate_args(session_id="test-session") is True
        assert tool.validate_args(session_id="test", status="pending") is True
        assert tool.validate_args(session_id="test", priority="high") is True

    def test_validate_args_invalid_session_id(self, tool):
        """Test argument validation with invalid session_id."""
        assert tool.validate_args(session_id="") is False
        assert tool.validate_args(session_id=None) is False

    def test_validate_args_invalid_status(self, tool):
        """Test argument validation with invalid status."""
        assert tool.validate_args(session_id="test", status="invalid") is False

    def test_validate_args_invalid_priority(self, tool):
        """Test argument validation with invalid priority."""
        assert tool.validate_args(session_id="test", priority="invalid") is False


class TestTodoWriteTool:
    """Test suite for TodoWriteTool."""

    @pytest.fixture
    def tool(self):
        """Provide a TodoWriteTool instance."""
        return TodoWriteTool()

    @pytest.fixture
    def storage(self):
        """Provide a fresh TodoStorage instance."""
        return TodoStorage()

    @pytest.mark.asyncio
    async def test_replace_action(self, tool, storage, monkeypatch):
        """Test replace action."""
        monkeypatch.setattr("src.infrastructure.agent.tools.todo_tools._todo_storage", storage)

        todos = [
            {"content": "New task 1"},
            {"content": "New task 2"},
        ]
        result = await tool.execute(session_id="session-1", action="replace", todos=todos)
        data = json.loads(result)

        assert data["success"] is True
        assert data["action"] == "replace"
        assert data["total_count"] == 2

        retrieved = storage.get("session-1")
        assert len(retrieved) == 2

    @pytest.mark.asyncio
    async def test_add_action(self, tool, storage, monkeypatch):
        """Test add action."""
        storage.add("session-1", TodoItem(id="1", content="Existing"))
        monkeypatch.setattr("src.infrastructure.agent.tools.todo_tools._todo_storage", storage)

        todos = [{"content": "New task"}]
        result = await tool.execute(session_id="session-1", action="add", todos=todos)
        data = json.loads(result)

        assert data["success"] is True
        assert data["action"] == "add"
        assert data["added_count"] == 1
        assert data["total_count"] == 2

    @pytest.mark.asyncio
    async def test_update_action(self, tool, storage, monkeypatch):
        """Test update action."""
        storage.add("session-1", TodoItem(id="todo-1", content="Original", status="pending"))
        monkeypatch.setattr("src.infrastructure.agent.tools.todo_tools._todo_storage", storage)

        todos = [{"status": "completed"}]
        result = await tool.execute(
            session_id="session-1",
            action="update",
            todo_id="todo-1",
            todos=todos,
        )
        data = json.loads(result)

        assert data["success"] is True
        assert data["action"] == "update"

        retrieved = storage.get("session-1")
        assert retrieved[0].status == "completed"

    @pytest.mark.asyncio
    async def test_update_action_without_todo_id(self, tool, storage, monkeypatch):
        """Test update action without todo_id returns error."""
        monkeypatch.setattr("src.infrastructure.agent.tools.todo_tools._todo_storage", storage)

        result = await tool.execute(
            session_id="session-1",
            action="update",
        )
        data = json.loads(result)

        assert data["success"] is False
        assert "error" in data

    @pytest.mark.asyncio
    async def test_update_nonexistent_todo(self, tool, storage, monkeypatch):
        """Test updating a todo that doesn't exist."""
        monkeypatch.setattr("src.infrastructure.agent.tools.todo_tools._todo_storage", storage)

        result = await tool.execute(
            session_id="session-1",
            action="update",
            todo_id="nonexistent",
        )
        data = json.loads(result)

        assert data["success"] is False

    def test_validate_args_valid(self, tool):
        """Test argument validation with valid args."""
        assert tool.validate_args(session_id="test", action="replace") is True
        assert tool.validate_args(session_id="test", action="add") is True
        assert tool.validate_args(session_id="test", action="update", todo_id="1") is True

    def test_validate_args_invalid_session_id(self, tool):
        """Test argument validation with invalid session_id."""
        assert tool.validate_args(session_id="", action="replace") is False

    def test_validate_args_invalid_action(self, tool):
        """Test argument validation with invalid action."""
        assert tool.validate_args(session_id="test", action="invalid") is False

    def test_validate_args_update_without_todo_id(self, tool):
        """Test update action without todo_id fails validation."""
        assert tool.validate_args(session_id="test", action="update") is False


class TestTodoIntegration:
    """Integration tests for todo tools working together."""

    @pytest.fixture
    def storage(self):
        """Provide a fresh TodoStorage instance."""
        return TodoStorage()

    def test_full_workflow(self, storage, monkeypatch):
        """Test complete workflow: write, read, update, read."""
        monkeypatch.setattr("src.infrastructure.agent.tools.todo_tools._todo_storage", storage)

        write_tool = TodoWriteTool()
        read_tool = TodoReadTool()

        import asyncio

        # Step 1: Create initial todos
        todos = [
            {"content": "Task 1", "priority": "high"},
            {"content": "Task 2", "priority": "medium"},
        ]

        async def run_workflow():
            await write_tool.execute(session_id="workflow-test", action="replace", todos=todos)

            # Step 2: Read todos
            read_result = await read_tool.execute(session_id="workflow-test")
            read_data = json.loads(read_result)
            assert read_data["total_count"] == 2

            # Step 3: Update first todo to in_progress
            await write_tool.execute(
                session_id="workflow-test",
                action="update",
                todo_id=read_data["todos"][0]["id"],
                todos=[{"status": "in_progress"}],
            )

            # Step 4: Read again to verify update
            read_result2 = await read_tool.execute(session_id="workflow-test")
            read_data2 = json.loads(read_result2)
            assert read_data2["todos"][0]["status"] == "in_progress"

            # Step 5: Add a new todo
            await write_tool.execute(
                session_id="workflow-test",
                action="add",
                todos=[{"content": "Task 3", "priority": "low"}],
            )

            # Step 6: Final read
            read_result3 = await read_tool.execute(session_id="workflow-test")
            read_data3 = json.loads(read_result3)
            assert read_data3["total_count"] == 3

        asyncio.run(run_workflow())
