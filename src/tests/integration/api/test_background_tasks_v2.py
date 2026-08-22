"""Production generation integration coverage for the background-tasks row."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI, status
from httpx import AsyncClient

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.plugins.v2.background_task_services import (
    BACKGROUND_TASK_MANAGER_SERVICE_V2,
    BackgroundTaskManagerRuntimeV2,
)

pytestmark = pytest.mark.integration


async def _noop() -> None:
    return None


@pytest.fixture(autouse=True)
async def _background_tasks_v2_runtime(
    test_app: FastAPI,
    test_user,
) -> AsyncIterator[None]:
    """Exercise task requests through the production generation dispatcher."""

    async def current_user_override():
        test_user.is_superuser = False
        return test_user

    test_app.dependency_overrides[get_current_user] = current_user_override
    await initialize_plugin_runtime_v2(test_app)
    assert "background-tasks" in test_app.state.platform_plugin_route_graph_v2.v2_owned_row_ids
    try:
        yield
    finally:
        await shutdown_plugin_runtime_v2(test_app)


async def test_list_background_tasks_uses_generation_manager_and_db_membership(
    authenticated_async_client: AsyncClient,
    test_app: FastAPI,
    test_project_db,
    test_user,
) -> None:
    host = test_app.state.platform_plugin_runtime_v2
    async with await host.acquire() as generation:
        runtime = generation.resolve(
            BACKGROUND_TASK_MANAGER_SERVICE_V2,
            ScopeV2(kind=ScopeKindV2.ROOT),
        )
        assert isinstance(runtime, BackgroundTaskManagerRuntimeV2)
        owned = runtime.manager.create_task("owned-v2", _noop)
        owned.owner_user_id = str(test_user.id)
        project_task = runtime.manager.create_task("project-v2", _noop)
        project_task.project_id = str(test_project_db.id)
        foreign = runtime.manager.create_task("foreign-v2", _noop)
        foreign.owner_user_id = "foreign-user"

    response = await authenticated_async_client.get("/api/v1/tasks/")

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["total"] == 2
    assert {task["task_id"] for task in payload["tasks"]} == {
        owned.task_id,
        project_task.task_id,
    }
    assert foreign.task_id in runtime.manager.tasks
