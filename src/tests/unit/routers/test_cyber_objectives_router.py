"""Unit tests for cyber objectives route error mapping."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, Response

from src.infrastructure.adapters.primary.web.routers import cyber_objectives


class _ObjectiveRepo:
    async def find_by_id(self, _objective_id: str) -> object:
        return SimpleNamespace(
            id="objective-secret",
            workspace_id="workspace-1",
            title="Objective",
            description="Description",
        )


class _TaskRepo:
    async def find_root_by_objective_id(self, *_args: object) -> object | None:
        return None


class _Container:
    def cyber_objective_repository(self) -> _ObjectiveRepo:
        return _ObjectiveRepo()

    def workspace_task_repository(self) -> _TaskRepo:
        return _TaskRepo()


@pytest.mark.unit
async def test_project_objective_to_task_sanitizes_task_access_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow_access(*_args: object, **_kwargs: object) -> None:
        return None

    class _TaskService:
        async def list_tasks(self, **_kwargs: object) -> list[object]:
            raise PermissionError("task access secret denied")

    monkeypatch.setattr(cyber_objectives, "require_workspace_access", allow_access)
    monkeypatch.setattr(cyber_objectives, "get_container_with_db", lambda _request, _db: _Container())
    monkeypatch.setattr(cyber_objectives, "_get_workspace_task_service", lambda _request, _db: _TaskService())

    with pytest.raises(HTTPException) as exc_info:
        await cyber_objectives.project_objective_to_task(
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
            objective_id="objective-secret",
            request=SimpleNamespace(),
            response=Response(),
            body=None,
            current_user=SimpleNamespace(id="user-1"),
            db=SimpleNamespace(rollback=AsyncMock(), commit=AsyncMock()),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Access denied"
    assert "secret" not in str(exc_info.value.detail)


@pytest.mark.unit
async def test_project_objective_to_task_sanitizes_create_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def allow_access(*_args: object, **_kwargs: object) -> None:
        return None

    class _TaskService:
        async def list_tasks(self, **_kwargs: object) -> list[object]:
            return []

    class _CommandService:
        async def create_task(self, **_kwargs: object) -> object:
            raise RuntimeError("task creation secret failed")

    db = SimpleNamespace(rollback=AsyncMock(), commit=AsyncMock())
    monkeypatch.setattr(cyber_objectives, "require_workspace_access", allow_access)
    monkeypatch.setattr(cyber_objectives, "get_container_with_db", lambda _request, _db: _Container())
    monkeypatch.setattr(cyber_objectives, "_get_workspace_task_service", lambda _request, _db: _TaskService())
    monkeypatch.setattr(
        cyber_objectives,
        "_get_workspace_task_command_service",
        lambda _request, _db: _CommandService(),
    )
    monkeypatch.setattr(
        cyber_objectives,
        "_get_workspace_task_event_publisher",
        lambda _request: SimpleNamespace(publish_pending_events=AsyncMock()),
    )

    with pytest.raises(HTTPException) as exc_info:
        await cyber_objectives.project_objective_to_task(
            tenant_id="tenant-1",
            project_id="project-1",
            workspace_id="workspace-1",
            objective_id="objective-secret",
            request=SimpleNamespace(),
            response=Response(),
            body=None,
            current_user=SimpleNamespace(id="user-1"),
            db=db,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Failed to project objective to task"
    assert "secret" not in str(exc_info.value.detail)
    db.rollback.assert_awaited_once()


@pytest.mark.unit
async def test_ensure_objective_root_task_exposes_pending_autonomy_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auto-projected roots must not silently consume their first activation tick."""

    class _CommandService:
        async def create_task(self, **kwargs: object) -> object:
            return SimpleNamespace(
                id="task-root-1",
                workspace_id=kwargs["workspace_id"],
                metadata=kwargs["metadata"],
            )

        def consume_pending_events(self) -> list[object]:
            return []

        def consume_pending_autonomy_ticks(self) -> list[tuple[str, str]]:
            return [("workspace-1", "user-1")]

    scheduled_ticks: list[tuple[str, str]] = []
    command_service = _CommandService()

    monkeypatch.setattr(cyber_objectives, "get_container_with_db", lambda _request, _db: _Container())
    monkeypatch.setattr(
        cyber_objectives,
        "_get_workspace_task_command_service",
        lambda _request, _db: command_service,
    )
    monkeypatch.setattr(
        cyber_objectives,
        "_get_workspace_task_event_publisher",
        lambda _request: SimpleNamespace(publish_pending_events=AsyncMock()),
    )
    monkeypatch.setattr(
        cyber_objectives,
        "schedule_autonomy_tick",
        lambda workspace_id, actor_user_id: scheduled_ticks.append(
            (workspace_id, actor_user_id)
        ),
    )

    result = await cyber_objectives._ensure_objective_root_task(
        request=SimpleNamespace(),
        db=SimpleNamespace(commit=AsyncMock()),
        workspace_id="workspace-1",
        current_user=SimpleNamespace(id="user-1", preferred_language="en-US"),
        objective=SimpleNamespace(
            id="objective-1",
            title="Objective",
            description="Description",
        ),
    )

    returned_ticks = list(result) if isinstance(result, (list, tuple)) else []
    assert scheduled_ticks == [("workspace-1", "user-1")] or returned_ticks == [
        ("workspace-1", "user-1")
    ]
