"""Tests for SqlWorkspaceTaskRepository."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.workspace_task import (
    WorkspaceTask,
    WorkspaceTaskPriority,
    WorkspaceTaskStatus,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository import (
    SqlWorkspaceTaskRepository,
)


@pytest.fixture
async def v2_workspace_task_repo(
    v2_db_session: AsyncSession,
    workspace_test_seed: dict[str, str],
) -> SqlWorkspaceTaskRepository:
    """Create a SqlWorkspaceTaskRepository for testing."""
    return SqlWorkspaceTaskRepository(v2_db_session)


def make_task(
    task_id: str,
    workspace_id: str = "workspace-1",
    title: str = "Task title",
    status: WorkspaceTaskStatus = WorkspaceTaskStatus.TODO,
    priority: WorkspaceTaskPriority = WorkspaceTaskPriority.NONE,
    created_at: datetime | None = None,
    metadata: dict[str, object] | None = None,
) -> WorkspaceTask:
    now = datetime.now(UTC)
    return WorkspaceTask(
        id=task_id,
        workspace_id=workspace_id,
        title=title,
        description="Task description",
        created_by="user-1",
        assignee_user_id="user-2",
        assignee_agent_id=None,
        status=status,
        priority=priority,
        metadata=metadata or {"priority": "medium"},
        created_at=created_at or now,
        updated_at=now,
    )


class TestSqlWorkspaceTaskRepository:
    """Tests for workspace task repository behavior."""

    @pytest.mark.asyncio
    async def test_save_and_find_by_id(
        self, v2_workspace_task_repo: SqlWorkspaceTaskRepository
    ) -> None:
        task = make_task("wt-1")
        await v2_workspace_task_repo.save(task)

        found = await v2_workspace_task_repo.find_by_id("wt-1")
        assert found is not None
        assert found.id == "wt-1"
        assert found.workspace_id == "workspace-1"
        assert found.status == WorkspaceTaskStatus.TODO
        assert found.priority == WorkspaceTaskPriority.NONE

    @pytest.mark.asyncio
    async def test_save_and_find_by_id_round_trips_priority(
        self, v2_workspace_task_repo: SqlWorkspaceTaskRepository
    ) -> None:
        task = make_task("wt-priority", priority=WorkspaceTaskPriority.P3)
        await v2_workspace_task_repo.save(task)

        found = await v2_workspace_task_repo.find_by_id("wt-priority")
        assert found is not None
        assert found.priority == WorkspaceTaskPriority.P3

    @pytest.mark.asyncio
    async def test_find_by_workspace_with_status_filter(
        self, v2_workspace_task_repo: SqlWorkspaceTaskRepository
    ) -> None:
        await v2_workspace_task_repo.save(
            make_task("wt-a", workspace_id="workspace-a", status=WorkspaceTaskStatus.TODO)
        )
        await v2_workspace_task_repo.save(
            make_task("wt-b", workspace_id="workspace-a", status=WorkspaceTaskStatus.IN_PROGRESS)
        )
        await v2_workspace_task_repo.save(
            make_task("wt-c", workspace_id="workspace-b", status=WorkspaceTaskStatus.DONE)
        )

        items = await v2_workspace_task_repo.find_by_workspace("workspace-a")
        assert len(items) == 2

        filtered = await v2_workspace_task_repo.find_by_workspace(
            "workspace-a", status=WorkspaceTaskStatus.IN_PROGRESS
        )
        assert len(filtered) == 1
        assert filtered[0].id == "wt-b"

    @pytest.mark.asyncio
    async def test_workspace_task_lists_use_id_tie_breakers(
        self, v2_workspace_task_repo: SqlWorkspaceTaskRepository
    ) -> None:
        created_at = datetime(2026, 1, 1, tzinfo=UTC)
        await v2_workspace_task_repo.save(
            make_task(
                "wt-b",
                workspace_id="workspace-list",
                created_at=created_at,
                metadata={"root_goal_task_id": "root-1"},
            )
        )
        await v2_workspace_task_repo.save(
            make_task(
                "wt-a",
                workspace_id="workspace-list",
                created_at=created_at,
                metadata={"root_goal_task_id": "root-1"},
            )
        )

        workspace_items = await v2_workspace_task_repo.find_by_workspace("workspace-list")
        root_items = await v2_workspace_task_repo.find_by_root_goal_task_id(
            "workspace-list", "root-1"
        )

        assert [item.id for item in workspace_items] == ["wt-a", "wt-b"]
        assert [item.id for item in root_items] == ["wt-a", "wt-b"]

    @pytest.mark.asyncio
    async def test_save_updates_existing_task(
        self, v2_workspace_task_repo: SqlWorkspaceTaskRepository
    ) -> None:
        await v2_workspace_task_repo.save(make_task("wt-upd", status=WorkspaceTaskStatus.TODO))

        updated = make_task("wt-upd", status=WorkspaceTaskStatus.DONE)
        updated.title = "Task done"
        await v2_workspace_task_repo.save(updated)

        found = await v2_workspace_task_repo.find_by_id("wt-upd")
        assert found is not None
        assert found.title == "Task done"
        assert found.status == WorkspaceTaskStatus.DONE

    @pytest.mark.asyncio
    async def test_delete_task(self, v2_workspace_task_repo: SqlWorkspaceTaskRepository) -> None:
        await v2_workspace_task_repo.save(make_task("wt-del"))

        deleted = await v2_workspace_task_repo.delete("wt-del")
        assert deleted is True
        assert await v2_workspace_task_repo.find_by_id("wt-del") is None
