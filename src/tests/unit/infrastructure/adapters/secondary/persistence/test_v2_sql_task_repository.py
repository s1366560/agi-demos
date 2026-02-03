"""
Tests for V2 SqlTaskRepository using BaseRepository.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.task.task_log import TaskLog
from src.infrastructure.adapters.secondary.persistence.models import TaskLog as DBTaskLog
from src.infrastructure.adapters.secondary.persistence.v2_sql_task_repository import (
    V2SqlTaskRepository,
)


@pytest.fixture
async def v2_task_repo(v2_db_session: AsyncSession) -> V2SqlTaskRepository:
    """Create a V2 task repository for testing."""
    return V2SqlTaskRepository(v2_db_session)


class TestV2SqlTaskRepositoryCreate:
    """Tests for creating tasks."""

    @pytest.mark.asyncio
    async def test_save_new_task(self, v2_task_repo: V2SqlTaskRepository):
        """Test saving a new task."""
        task = TaskLog(
            id="task-test-1",
            group_id="group-1",
            task_type="test_task",
            status="PENDING",
            payload={"test": "data"},
            entity_id=None,
            entity_type=None,
            parent_task_id=None,
            worker_id=None,
            retry_count=0,
            error_message=None,
            created_at=datetime.now(timezone.utc),
            started_at=None,
            completed_at=None,
            stopped_at=None,
        )

        await v2_task_repo.save(task)

        retrieved = await v2_task_repo.find_by_id("task-test-1")
        assert retrieved is not None
        assert retrieved.id == "task-test-1"
        assert retrieved.group_id == "group-1"
        assert retrieved.status == "PENDING"


class TestV2SqlTaskRepositoryUpdate:
    """Tests for updating tasks."""

    @pytest.mark.asyncio
    async def test_update_existing_task(self, v2_task_repo: V2SqlTaskRepository):
        """Test updating an existing task."""
        task = TaskLog(
            id="task-update-1",
            group_id="group-1",
            task_type="test_task",
            status="PENDING",
            payload={},
            entity_id=None,
            entity_type=None,
            parent_task_id=None,
            worker_id=None,
            retry_count=0,
            error_message=None,
            created_at=datetime.now(timezone.utc),
            started_at=None,
            completed_at=None,
            stopped_at=None,
        )
        await v2_task_repo.save(task)

        updated = TaskLog(
            id="task-update-1",
            group_id="group-1",
            task_type="test_task",
            status="COMPLETED",
            payload={},
            entity_id=None,
            entity_type=None,
            parent_task_id=None,
            worker_id="worker-1",
            retry_count=0,
            error_message=None,
            created_at=task.created_at,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            stopped_at=None,
        )
        await v2_task_repo.save(updated)

        retrieved = await v2_task_repo.find_by_id("task-update-1")
        assert retrieved.status == "COMPLETED"
        assert retrieved.worker_id == "worker-1"
        assert retrieved.completed_at is not None


class TestV2SqlTaskRepositoryFind:
    """Tests for finding tasks."""

    @pytest.mark.asyncio
    async def test_find_by_id_existing(self, v2_task_repo: V2SqlTaskRepository):
        """Test finding an existing task by ID."""
        task = TaskLog(
            id="task-find-1",
            group_id="group-1",
            task_type="test_task",
            status="PENDING",
            payload={},
            entity_id=None,
            entity_type=None,
            parent_task_id=None,
            worker_id=None,
            retry_count=0,
            error_message=None,
            created_at=datetime.now(timezone.utc),
            started_at=None,
            completed_at=None,
            stopped_at=None,
        )
        await v2_task_repo.save(task)

        retrieved = await v2_task_repo.find_by_id("task-find-1")
        assert retrieved is not None
        assert retrieved.id == "task-find-1"

    @pytest.mark.asyncio
    async def test_find_by_id_not_found(self, v2_task_repo: V2SqlTaskRepository):
        """Test finding a non-existent task returns None."""
        retrieved = await v2_task_repo.find_by_id("non-existent")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_find_by_group(self, v2_task_repo: V2SqlTaskRepository):
        """Test listing tasks by group ID."""
        for i in range(3):
            task = TaskLog(
                id=f"task-group-{i}",
                group_id="group-list",
                task_type="test_task",
                status="PENDING",
                payload={"index": i},
                entity_id=None,
                entity_type=None,
                parent_task_id=None,
                worker_id=None,
                retry_count=0,
                error_message=None,
                created_at=datetime.now(timezone.utc),
                started_at=None,
                completed_at=None,
                stopped_at=None,
            )
            await v2_task_repo.save(task)

        tasks = await v2_task_repo.find_by_group("group-list")
        assert len(tasks) == 3

    @pytest.mark.asyncio
    async def test_list_recent(self, v2_task_repo: V2SqlTaskRepository):
        """Test listing recent tasks."""
        for i in range(5):
            task = TaskLog(
                id=f"task-recent-{i}",
                group_id="group-recent",
                task_type="test_task",
                status="PENDING",
                payload={},
                entity_id=None,
                entity_type=None,
                parent_task_id=None,
                worker_id=None,
                retry_count=0,
                error_message=None,
                created_at=datetime.now(timezone.utc),
                started_at=None,
                completed_at=None,
                stopped_at=None,
            )
            await v2_task_repo.save(task)

        tasks = await v2_task_repo.list_recent(limit=3)
        assert len(tasks) == 3

    @pytest.mark.asyncio
    async def test_list_by_status(self, v2_task_repo: V2SqlTaskRepository):
        """Test listing tasks by status."""
        for status in ["PENDING", "PROCESSING", "COMPLETED"]:
            task = TaskLog(
                id=f"task-status-{status}",
                group_id="group-status",
                task_type="test_task",
                status=status,
                payload={},
                entity_id=None,
                entity_type=None,
                parent_task_id=None,
                worker_id=None,
                retry_count=0,
                error_message=None,
                created_at=datetime.now(timezone.utc),
                started_at=None,
                completed_at=None,
                stopped_at=None,
            )
            await v2_task_repo.save(task)

        pending_tasks = await v2_task_repo.list_by_status("PENDING")
        assert len(pending_tasks) == 1
        assert pending_tasks[0].status == "PENDING"


class TestV2SqlTaskRepositoryDelete:
    """Tests for deleting tasks."""

    @pytest.mark.asyncio
    async def test_delete_existing_task(self, v2_task_repo: V2SqlTaskRepository):
        """Test deleting an existing task."""
        task = TaskLog(
            id="task-delete-1",
            group_id="group-1",
            task_type="test_task",
            status="PENDING",
            payload={},
            entity_id=None,
            entity_type=None,
            parent_task_id=None,
            worker_id=None,
            retry_count=0,
            error_message=None,
            created_at=datetime.now(timezone.utc),
            started_at=None,
            completed_at=None,
            stopped_at=None,
        )
        await v2_task_repo.save(task)

        await v2_task_repo.delete("task-delete-1")

        retrieved = await v2_task_repo.find_by_id("task-delete-1")
        assert retrieved is None


class TestV2SqlTaskRepositoryToDomain:
    """Tests for _to_domain conversion."""

    def test_to_domain_with_none(self, v2_task_repo: V2SqlTaskRepository):
        """Test that _to_domain returns None for None input."""
        result = v2_task_repo._to_domain(None)
        assert result is None


class TestV2SqlTaskRepositoryToDb:
    """Tests for _to_db conversion."""

    def test_to_db_creates_db_model(self, v2_task_repo: V2SqlTaskRepository):
        """Test that _to_db creates a valid DB model."""
        task = TaskLog(
            id="task-todb-1",
            group_id="group-1",
            task_type="test_task",
            status="PENDING",
            payload={},
            entity_id=None,
            entity_type=None,
            parent_task_id=None,
            worker_id=None,
            retry_count=0,
            error_message=None,
            created_at=datetime.now(timezone.utc),
            started_at=None,
            completed_at=None,
            stopped_at=None,
        )

        db_model = v2_task_repo._to_db(task)
        assert isinstance(db_model, DBTaskLog)
        assert db_model.id == "task-todb-1"
        assert db_model.group_id == "group-1"
