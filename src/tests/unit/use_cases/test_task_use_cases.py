"""
Unit tests for Task use cases.
"""

from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest

from src.application.use_cases.task.create_task import CreateTaskCommand, CreateTaskUseCase
from src.application.use_cases.task.get_task import GetTaskQuery, GetTaskUseCase
from src.application.use_cases.task.list_tasks import ListTasksQuery, ListTasksUseCase
from src.application.use_cases.task.update_task import UpdateTaskCommand, UpdateTaskUseCase
from src.domain.model.task.task_log import TaskLog


@pytest.mark.unit
class TestCreateTaskUseCase:
    """Test cases for CreateTaskUseCase"""

    @pytest.mark.asyncio
    async def test_create_task_with_all_fields(self):
        """Test creating a task with all fields provided"""
        # Arrange
        mock_repo = Mock()
        mock_repo.save = AsyncMock()

        use_case = CreateTaskUseCase(mock_repo)
        command = CreateTaskCommand(
            group_id="group_123",
            task_type="test_task",
            payload={"key": "value"},
            entity_id="entity_123",
            entity_type="memory",
            parent_task_id="parent_123",
        )

        # Act
        result = await use_case.execute(command)

        # Assert
        assert result.group_id == "group_123"
        assert result.task_type == "test_task"
        assert result.payload == {"key": "value"}
        assert result.entity_id == "entity_123"
        assert result.entity_type == "memory"
        assert result.parent_task_id == "parent_123"
        assert result.status == "PENDING"  # Default status
        assert result.id is not None
        assert isinstance(result.created_at, datetime)
        mock_repo.save.assert_called_once_with(result)

    @pytest.mark.asyncio
    async def test_create_task_with_defaults(self):
        """Test creating a task with default values"""
        # Arrange
        mock_repo = Mock()
        mock_repo.save = AsyncMock()

        use_case = CreateTaskUseCase(mock_repo)
        command = CreateTaskCommand(group_id="group_123", task_type="test_task")

        # Act
        result = await use_case.execute(command)

        # Assert
        assert result.group_id == "group_123"
        assert result.task_type == "test_task"
        assert result.payload == {}  # Default
        assert result.entity_id is None
        assert result.entity_type is None
        assert result.parent_task_id is None
        assert result.status == "PENDING"
        mock_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_task_with_none_payload(self):
        """Test creating a task with None payload converts to empty dict"""
        # Arrange
        mock_repo = Mock()
        mock_repo.save = AsyncMock()

        use_case = CreateTaskUseCase(mock_repo)
        command = CreateTaskCommand(group_id="group_123", task_type="test_task", payload=None)

        # Act
        result = await use_case.execute(command)

        # Assert
        assert result.payload == {}
        mock_repo.save.assert_called_once()


@pytest.mark.unit
class TestGetTaskUseCase:
    """Test cases for GetTaskUseCase"""

    @pytest.mark.asyncio
    async def test_get_task_success(self):
        """Test getting a task successfully"""
        # Arrange
        task = TaskLog(id="task_123", group_id="group_123", task_type="test_task", status="PENDING")

        mock_repo = Mock()
        mock_repo.find_by_id = AsyncMock(return_value=task)

        use_case = GetTaskUseCase(mock_repo)
        query = GetTaskQuery(task_id="task_123")

        # Act
        result = await use_case.execute(query)

        # Assert
        assert result is not None
        assert result.id == "task_123"
        assert result.group_id == "group_123"
        assert result.status == "PENDING"
        mock_repo.find_by_id.assert_called_once_with("task_123")

    @pytest.mark.asyncio
    async def test_get_task_not_found(self):
        """Test getting a non-existent task"""
        # Arrange
        mock_repo = Mock()
        mock_repo.find_by_id = AsyncMock(return_value=None)

        use_case = GetTaskUseCase(mock_repo)
        query = GetTaskQuery(task_id="nonexistent")

        # Act
        result = await use_case.execute(query)

        # Assert
        assert result is None
        mock_repo.find_by_id.assert_called_once_with("nonexistent")


@pytest.mark.unit
class TestListTasksUseCase:
    """Test cases for ListTasksUseCase"""

    @pytest.mark.asyncio
    async def test_list_tasks_by_group_id(self):
        """Test listing tasks by group ID"""
        # Arrange
        tasks = [
            TaskLog(id="task_1", group_id="group_123", task_type="test", status="PENDING"),
            TaskLog(id="task_2", group_id="group_123", task_type="test", status="PROCESSING"),
        ]

        mock_repo = Mock()
        mock_repo.find_by_group = AsyncMock(return_value=tasks)

        use_case = ListTasksUseCase(mock_repo)
        query = ListTasksQuery(group_id="group_123", limit=10, offset=0)

        # Act
        result = await use_case.execute(query)

        # Assert
        assert len(result) == 2
        assert result[0].id == "task_1"
        assert result[1].id == "task_2"
        mock_repo.find_by_group.assert_called_once_with("group_123", limit=10, offset=0)

    @pytest.mark.asyncio
    async def test_list_tasks_by_status(self):
        """Test listing tasks by status"""
        # Arrange
        tasks = [
            TaskLog(id="task_1", group_id="group_1", task_type="test", status="FAILED"),
            TaskLog(id="task_2", group_id="group_2", task_type="test", status="FAILED"),
        ]

        mock_repo = Mock()
        mock_repo.list_by_status = AsyncMock(return_value=tasks)

        use_case = ListTasksUseCase(mock_repo)
        query = ListTasksQuery(status="FAILED", limit=20, offset=0)

        # Act
        result = await use_case.execute(query)

        # Assert
        assert len(result) == 2
        assert all(t.status == "FAILED" for t in result)
        mock_repo.list_by_status.assert_called_once_with("FAILED", limit=20, offset=0)

    @pytest.mark.asyncio
    async def test_list_recent_tasks(self):
        """Test listing recent tasks without filters"""
        # Arrange
        tasks = [
            TaskLog(id="task_1", group_id="group_1", task_type="test", status="COMPLETED"),
            TaskLog(id="task_2", group_id="group_2", task_type="test", status="PENDING"),
        ]

        mock_repo = Mock()
        mock_repo.list_recent = AsyncMock(return_value=tasks)

        use_case = ListTasksUseCase(mock_repo)
        query = ListTasksQuery(limit=100)

        # Act
        result = await use_case.execute(query)

        # Assert
        assert len(result) == 2
        mock_repo.list_recent.assert_called_once_with(limit=100)

    @pytest.mark.asyncio
    async def test_list_tasks_empty_result(self):
        """Test listing tasks when no tasks match"""
        # Arrange
        mock_repo = Mock()
        mock_repo.find_by_group = AsyncMock(return_value=[])

        use_case = ListTasksUseCase(mock_repo)
        query = ListTasksQuery(group_id="empty_group")

        # Act
        result = await use_case.execute(query)

        # Assert
        assert result == []
        mock_repo.find_by_group.assert_called_once()


@pytest.mark.unit
class TestUpdateTaskUseCase:
    """Test cases for UpdateTaskUseCase"""

    @pytest.mark.asyncio
    async def test_update_task_status(self):
        """Test updating task status"""
        # Arrange
        task = TaskLog(id="task_123", group_id="group_123", task_type="test_task", status="PENDING")

        mock_repo = Mock()
        mock_repo.find_by_id = AsyncMock(return_value=task)
        mock_repo.save = AsyncMock()

        use_case = UpdateTaskUseCase(mock_repo)
        command = UpdateTaskCommand(task_id="task_123", status="PROCESSING")

        # Act
        result = await use_case.execute(command)

        # Assert
        assert result is not None
        assert result.status == "PROCESSING"
        mock_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_task_all_fields(self):
        """Test updating all task fields"""
        # Arrange
        started_at = datetime.utcnow()
        completed_at = datetime.utcnow()

        task = TaskLog(id="task_123", group_id="group_123", task_type="test_task", status="PENDING")

        mock_repo = Mock()
        mock_repo.find_by_id = AsyncMock(return_value=task)
        mock_repo.save = AsyncMock()

        use_case = UpdateTaskUseCase(mock_repo)
        command = UpdateTaskCommand(
            task_id="task_123",
            status="COMPLETED",
            error_message=None,
            started_at=started_at,
            completed_at=completed_at,
            worker_id="worker_1",
        )

        # Act
        result = await use_case.execute(command)

        # Assert
        assert result.status == "COMPLETED"
        assert result.started_at == started_at
        assert result.completed_at == completed_at
        assert result.worker_id == "worker_1"
        mock_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_task_with_error(self):
        """Test updating a task with error message"""
        # Arrange
        task = TaskLog(
            id="task_123", group_id="group_123", task_type="test_task", status="PROCESSING"
        )

        mock_repo = Mock()
        mock_repo.find_by_id = AsyncMock(return_value=task)
        mock_repo.save = AsyncMock()

        use_case = UpdateTaskUseCase(mock_repo)
        command = UpdateTaskCommand(
            task_id="task_123", status="FAILED", error_message="Task failed due to timeout"
        )

        # Act
        result = await use_case.execute(command)

        # Assert
        assert result.status == "FAILED"
        assert result.error_message == "Task failed due to timeout"
        mock_repo.save.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_task_not_found(self):
        """Test updating a non-existent task"""
        # Arrange
        mock_repo = Mock()
        mock_repo.find_by_id = AsyncMock(return_value=None)

        use_case = UpdateTaskUseCase(mock_repo)
        command = UpdateTaskCommand(task_id="nonexistent", status="COMPLETED")

        # Act
        result = await use_case.execute(command)

        # Assert
        assert result is None
        mock_repo.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_update_task_partial_fields(self):
        """Test updating only some task fields"""
        # Arrange
        task = TaskLog(id="task_123", group_id="group_123", task_type="test_task", status="PENDING")

        mock_repo = Mock()
        mock_repo.find_by_id = AsyncMock(return_value=task)
        mock_repo.save = AsyncMock()

        use_case = UpdateTaskUseCase(mock_repo)
        command = UpdateTaskCommand(task_id="task_123", worker_id="worker_1")

        # Act
        result = await use_case.execute(command)

        # Assert
        assert result.status == "PENDING"  # Unchanged
        assert result.worker_id == "worker_1"  # Updated
        mock_repo.save.assert_called_once()
