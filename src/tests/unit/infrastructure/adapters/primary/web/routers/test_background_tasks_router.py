from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException, status

from src.infrastructure.adapters.primary.web.routers import background_tasks as router_mod
from src.infrastructure.adapters.secondary.background_tasks import TaskManager


class _ScalarResult:
    def __init__(self, values: set[str]) -> None:
        self._values = values

    def scalars(self) -> "_ScalarResult":
        return self

    def all(self) -> list[str]:
        return list(self._values)


class _Session:
    def __init__(self, project_ids: set[str]) -> None:
        self.project_ids = project_ids
        self.execute_calls = 0

    async def execute(self, _statement: object) -> _ScalarResult:
        self.execute_calls += 1
        return _ScalarResult(self.project_ids)


async def _noop() -> None:
    return None


def _user(user_id: str, *, is_superuser: bool = False) -> Any:
    return SimpleNamespace(id=user_id, is_superuser=is_superuser)


def _tracked_task(
    manager: TaskManager,
    task_type: str,
    *,
    owner_user_id: str | None = None,
    project_id: str | None = None,
    created_at: datetime,
) -> str:
    task = manager.create_task(task_type, _noop)
    task.owner_user_id = owner_user_id
    task.project_id = project_id
    task.created_at = created_at
    return task.task_id


@pytest.fixture
def task_manager(monkeypatch: pytest.MonkeyPatch) -> TaskManager:
    manager = TaskManager()
    monkeypatch.setattr(router_mod, "task_manager", manager)
    return manager


@pytest.mark.asyncio
async def test_list_tasks_filters_to_owner_or_project_member(task_manager: TaskManager) -> None:
    now = datetime.now(UTC)
    owned_id = _tracked_task(
        task_manager,
        "owned",
        owner_user_id="user-1",
        created_at=now,
    )
    project_id = _tracked_task(
        task_manager,
        "project",
        project_id="project-access",
        created_at=now - timedelta(minutes=1),
    )
    _foreign_id = _tracked_task(
        task_manager,
        "foreign",
        owner_user_id="user-2",
        project_id="project-foreign",
        created_at=now - timedelta(minutes=2),
    )
    _unscoped_id = _tracked_task(
        task_manager,
        "unscoped",
        created_at=now - timedelta(minutes=3),
    )

    response = await router_mod.list_tasks(
        status=None,
        limit=1,
        current_user=_user("user-1"),
        db=_Session({"project-access"}),
    )

    assert response["total"] == 2
    assert [task["task_id"] for task in response["tasks"]] == [owned_id]
    assert project_id in task_manager.tasks


@pytest.mark.asyncio
async def test_list_tasks_superuser_can_see_unscoped_tasks(task_manager: TaskManager) -> None:
    now = datetime.now(UTC)
    unscoped_id = _tracked_task(task_manager, "unscoped", created_at=now)
    session = _Session(set())

    response = await router_mod.list_tasks(
        status=None,
        limit=50,
        current_user=_user("admin", is_superuser=True),
        db=session,
    )

    assert response["total"] == 1
    assert [task["task_id"] for task in response["tasks"]] == [unscoped_id]
    assert session.execute_calls == 0


@pytest.mark.asyncio
async def test_get_task_status_rejects_inaccessible_task(task_manager: TaskManager) -> None:
    task_id = _tracked_task(
        task_manager,
        "foreign",
        owner_user_id="user-2",
        project_id="project-foreign",
        created_at=datetime.now(UTC),
    )

    with pytest.raises(HTTPException) as exc_info:
        await router_mod.get_task_status(
            task_id,
            current_user=_user("user-1"),
            db=_Session(set()),
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_cancel_task_rejects_inaccessible_task(task_manager: TaskManager) -> None:
    task_id = _tracked_task(
        task_manager,
        "foreign",
        owner_user_id="user-2",
        project_id="project-foreign",
        created_at=datetime.now(UTC),
    )

    with pytest.raises(HTTPException) as exc_info:
        await router_mod.cancel_task(
            task_id,
            current_user=_user("user-1"),
            db=_Session(set()),
        )

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.asyncio
async def test_cancel_task_allows_project_member(task_manager: TaskManager) -> None:
    task_id = _tracked_task(
        task_manager,
        "project",
        project_id="project-access",
        created_at=datetime.now(UTC),
    )

    response = await router_mod.cancel_task(
        task_id,
        current_user=_user("user-1"),
        db=_Session({"project-access"}),
    )

    assert response == {
        "status": "success",
        "message": f"Task {task_id} cancelled",
        "task_id": task_id,
    }
