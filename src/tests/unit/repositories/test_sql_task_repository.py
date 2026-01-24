"""
Unit tests for SqlAlchemyTaskRepository.
"""

from datetime import datetime

import pytest

from src.domain.model.task.task_log import TaskLog
from src.infrastructure.adapters.secondary.persistence.sql_task_repository import (
    SqlAlchemyTaskRepository,
)


@pytest.mark.unit
class TestSqlAlchemyTaskRepository:
    """Test cases for SqlAlchemyTaskRepository"""

    @pytest.mark.asyncio
    async def test_save_new_task(self, test_db):
        """Test saving a new task to the database"""
        # Arrange
        repo = SqlAlchemyTaskRepository(test_db)
        task = TaskLog(
            id="task_test_1",
            group_id="group_123",
            task_type="test_task",
            status="PENDING",
            payload={"key": "value"},
        )

        # Act
        await repo.save(task)
        await test_db.commit()

        # Assert
        result = await repo.find_by_id("task_test_1")
        assert result is not None
        assert result.id == "task_test_1"
        assert result.group_id == "group_123"
        assert result.task_type == "test_task"
        assert result.status == "PENDING"
        assert result.payload == {"key": "value"}

    @pytest.mark.asyncio
    async def test_save_update_existing_task(self, test_db):
        """Test updating an existing task"""
        # Arrange
        repo = SqlAlchemyTaskRepository(test_db)
        task = TaskLog(
            id="task_test_2", group_id="group_123", task_type="test_task", status="PENDING"
        )
        await repo.save(task)
        await test_db.commit()

        # Act - Update the task
        task.status = "COMPLETED"
        task.error_message = None
        task.completed_at = datetime.utcnow()
        await repo.save(task)
        await test_db.commit()

        # Assert
        result = await repo.find_by_id("task_test_2")
        assert result is not None
        assert result.status == "COMPLETED"
        assert result.completed_at is not None

    @pytest.mark.asyncio
    async def test_find_by_id_success(self, test_db):
        """Test finding a task by ID"""
        # Arrange
        repo = SqlAlchemyTaskRepository(test_db)
        task = TaskLog(
            id="task_test_3", group_id="group_123", task_type="test_task", status="PROCESSING"
        )
        await repo.save(task)
        await test_db.commit()

        # Act
        result = await repo.find_by_id("task_test_3")

        # Assert
        assert result is not None
        assert result.id == "task_test_3"
        assert result.status == "PROCESSING"

    @pytest.mark.asyncio
    async def test_find_by_id_not_found(self, test_db):
        """Test finding a non-existent task by ID"""
        # Arrange
        repo = SqlAlchemyTaskRepository(test_db)

        # Act
        result = await repo.find_by_id("nonexistent_task")

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_find_by_group(self, test_db):
        """Test finding all tasks in a group"""
        # Arrange
        repo = SqlAlchemyTaskRepository(test_db)
        task1 = TaskLog(
            id="task_test_4a", group_id="group_123", task_type="test_task", status="PENDING"
        )
        task2 = TaskLog(
            id="task_test_4b", group_id="group_123", task_type="test_task", status="PROCESSING"
        )
        task3 = TaskLog(
            id="task_test_4c", group_id="group_456", task_type="test_task", status="PENDING"
        )
        await repo.save(task1)
        await repo.save(task2)
        await repo.save(task3)
        await test_db.commit()

        # Act
        results = await repo.find_by_group("group_123")

        # Assert
        assert len(results) == 2
        task_ids = [t.id for t in results]
        assert "task_test_4a" in task_ids
        assert "task_test_4b" in task_ids
        assert "task_test_4c" not in task_ids

    @pytest.mark.asyncio
    async def test_find_by_group_with_pagination(self, test_db):
        """Test finding tasks in a group with pagination"""
        # Arrange
        repo = SqlAlchemyTaskRepository(test_db)
        for i in range(5):
            task = TaskLog(
                id=f"task_test_5_{i}", group_id="group_123", task_type="test_task", status="PENDING"
            )
            await repo.save(task)
        await test_db.commit()

        # Act
        results = await repo.find_by_group("group_123", limit=2, offset=2)

        # Assert
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_list_recent(self, test_db):
        """Test listing recent tasks"""
        # Arrange
        repo = SqlAlchemyTaskRepository(test_db)
        task1 = TaskLog(
            id="task_test_6a", group_id="group_1", task_type="test_task", status="COMPLETED"
        )
        task2 = TaskLog(
            id="task_test_6b", group_id="group_2", task_type="test_task", status="PENDING"
        )
        await repo.save(task1)
        await repo.save(task2)
        await test_db.commit()

        # Act
        results = await repo.list_recent(limit=10)

        # Assert
        assert len(results) >= 2
        task_ids = [t.id for t in results]
        assert "task_test_6a" in task_ids
        assert "task_test_6b" in task_ids

    @pytest.mark.asyncio
    async def test_list_by_status(self, test_db):
        """Test listing tasks by status"""
        # Arrange
        repo = SqlAlchemyTaskRepository(test_db)
        task1 = TaskLog(
            id="task_test_7a", group_id="group_1", task_type="test_task", status="FAILED"
        )
        task2 = TaskLog(
            id="task_test_7b", group_id="group_2", task_type="test_task", status="FAILED"
        )
        task3 = TaskLog(
            id="task_test_7c", group_id="group_3", task_type="test_task", status="COMPLETED"
        )
        await repo.save(task1)
        await repo.save(task2)
        await repo.save(task3)
        await test_db.commit()

        # Act
        results = await repo.list_by_status("FAILED")

        # Assert
        assert len(results) == 2
        task_ids = [t.id for t in results]
        assert "task_test_7a" in task_ids
        assert "task_test_7b" in task_ids
        assert "task_test_7c" not in task_ids

    @pytest.mark.asyncio
    async def test_delete_task(self, test_db):
        """Test deleting a task"""
        # Arrange
        repo = SqlAlchemyTaskRepository(test_db)
        task = TaskLog(
            id="task_test_8", group_id="group_123", task_type="test_task", status="PENDING"
        )
        await repo.save(task)
        await test_db.commit()

        # Verify it exists
        assert await repo.find_by_id("task_test_8") is not None

        # Act
        await repo.delete("task_test_8")
        await test_db.commit()

        # Assert
        result = await repo.find_by_id("task_test_8")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_task(self, test_db):
        """Test deleting a non-existent task (should not raise error)"""
        # Arrange
        repo = SqlAlchemyTaskRepository(test_db)

        # Act - Should not raise an error
        await repo.delete("nonexistent_task")
        await test_db.commit()

        # Assert - No exception raised

    @pytest.mark.asyncio
    async def test_to_domain_conversion(self, test_db):
        """Test conversion from DB model to domain model"""
        # Arrange
        repo = SqlAlchemyTaskRepository(test_db)
        created_at = datetime.utcnow()
        payload = {"test": "data", "nested": {"key": "value"}}
        task = TaskLog(
            id="task_test_9",
            group_id="group_123",
            task_type="conversion_task",
            status="PENDING",
            payload=payload,
            entity_id="entity_123",
            entity_type="memory",
            parent_task_id="parent_123",
            worker_id="worker_123",
            retry_count=3,
            error_message="Test error",
            created_at=created_at,
        )
        await repo.save(task)
        await test_db.commit()

        # Act
        result = await repo.find_by_id("task_test_9")

        # Assert
        assert result is not None
        assert isinstance(result, TaskLog)
        assert result.id == "task_test_9"
        assert result.group_id == "group_123"
        assert result.task_type == "conversion_task"
        assert result.status == "PENDING"
        assert result.payload == payload
        assert result.entity_id == "entity_123"
        assert result.entity_type == "memory"
        assert result.parent_task_id == "parent_123"
        assert result.worker_id == "worker_123"
        assert result.retry_count == 3
        assert result.error_message == "Test error"
        assert isinstance(result.created_at, datetime)
