"""Unit tests for workspace task router mutation pipeline behavior."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, status
from fastapi.testclient import TestClient

from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskStatus


def _make_task(
    task_id: str = "wt-1",
    status_value: WorkspaceTaskStatus = WorkspaceTaskStatus.TODO,
) -> WorkspaceTask:
    return WorkspaceTask(
        id=task_id,
        workspace_id="ws-1",
        title="Team Task",
        description="Task description",
        created_by="user-1",
        status=status_value,
        metadata={"source": "test"},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@pytest.fixture
def mock_task_service() -> AsyncMock:
    service = AsyncMock()
    service.list_tasks = AsyncMock(return_value=[_make_task()])
    service.get_task = AsyncMock(return_value=_make_task())
    return service


@pytest.fixture
def mock_command_service() -> AsyncMock:
    service = AsyncMock()
    service.complete_task = AsyncMock(
        return_value=_make_task(status_value=WorkspaceTaskStatus.DONE)
    )
    service.consume_pending_events = Mock(return_value=["queued-event"])
    return service


@pytest.fixture
def mock_event_publisher() -> AsyncMock:
    publisher = AsyncMock()
    publisher.publish_pending_events = AsyncMock(return_value=None)
    return publisher


@pytest.fixture
def workspace_tasks_client(
    monkeypatch: pytest.MonkeyPatch,
    mock_task_service: AsyncMock,
    mock_command_service: AsyncMock,
    mock_event_publisher: AsyncMock,
) -> TestClient:
    from src.infrastructure.adapters.primary.web.dependencies import get_current_user
    from src.infrastructure.adapters.primary.web.routers import workspace_tasks
    from src.infrastructure.adapters.secondary.persistence.database import get_db

    app = FastAPI()
    app.include_router(workspace_tasks.router)

    mock_db = AsyncMock()
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    async def override_get_db():
        yield mock_db

    user = Mock()
    user.id = "user-1"

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user

    monkeypatch.setattr(
        workspace_tasks, "_get_workspace_task_service", lambda request, db: mock_task_service
    )
    monkeypatch.setattr(
        workspace_tasks,
        "_get_workspace_task_command_service",
        lambda request, db: mock_command_service,
    )
    monkeypatch.setattr(
        workspace_tasks,
        "_get_workspace_task_event_publisher",
        lambda request: mock_event_publisher,
    )

    client = TestClient(app)
    client.mock_db = mock_db  # type: ignore[attr-defined]
    return client


@pytest.mark.unit
class TestWorkspaceTasksRouter:
    def test_complete_commits_before_publishing_events(
        self,
        workspace_tasks_client: TestClient,
        mock_command_service: AsyncMock,
        mock_event_publisher: AsyncMock,
    ) -> None:
        call_order: list[str] = []

        async def _complete_task(**_: object) -> WorkspaceTask:
            call_order.append("command")
            return _make_task(status_value=WorkspaceTaskStatus.DONE)

        async def _commit() -> None:
            call_order.append("commit")

        async def _publish(events: object) -> None:
            assert events == ["queued-event"]
            call_order.append("publish")

        mock_command_service.complete_task.side_effect = _complete_task
        workspace_tasks_client.mock_db.commit.side_effect = _commit  # type: ignore[attr-defined]
        mock_event_publisher.publish_pending_events.side_effect = _publish

        response = workspace_tasks_client.post("/api/v1/workspaces/ws-1/tasks/wt-1/complete")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] == "done"
        assert call_order == ["command", "commit", "publish"]

    def test_complete_still_succeeds_when_post_commit_publish_fails(
        self,
        workspace_tasks_client: TestClient,
        mock_event_publisher: AsyncMock,
    ) -> None:
        mock_event_publisher.publish_pending_events.side_effect = RuntimeError("redis unavailable")

        response = workspace_tasks_client.post("/api/v1/workspaces/ws-1/tasks/wt-1/complete")

        assert response.status_code == status.HTTP_200_OK
        assert workspace_tasks_client.mock_db.commit.await_count == 1  # type: ignore[attr-defined]
