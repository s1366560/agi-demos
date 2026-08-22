from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from fastapi import FastAPI

from src.infrastructure.adapters.primary.web.routers import (
    background_tasks as router_mod,
    tasks as tasks_router_mod,
)
from src.infrastructure.plugins.v2.background_task_services import BackgroundTaskPageV2


def _user(user_id: str, *, is_superuser: bool = False) -> Any:
    return SimpleNamespace(id=user_id, is_superuser=is_superuser)


async def test_list_tasks_delegates_owner_and_project_filtering_to_v2_service() -> None:
    services = SimpleNamespace(
        list_tasks=AsyncMock(
            return_value=BackgroundTaskPageV2(
                tasks=({"task_id": "owned"},),
                total=2,
            )
        )
    )

    response = await router_mod.list_tasks(
        status=None,
        limit=1,
        current_user=_user("user-1"),
        background_task_application=SimpleNamespace(services=services),
    )

    assert response["total"] == 2
    assert [task["task_id"] for task in response["tasks"]] == ["owned"]
    services.list_tasks.assert_awaited_once_with(
        user_id="user-1",
        is_superuser=False,
        status=None,
        limit=1,
    )


async def test_list_tasks_delegates_superuser_visibility_to_v2_service() -> None:
    services = SimpleNamespace(
        list_tasks=AsyncMock(
            return_value=BackgroundTaskPageV2(
                tasks=({"task_id": "unscoped"},),
                total=1,
            )
        )
    )

    response = await router_mod.list_tasks(
        status=None,
        limit=50,
        current_user=_user("admin", is_superuser=True),
        background_task_application=SimpleNamespace(services=services),
    )

    assert response["total"] == 1
    assert [task["task_id"] for task in response["tasks"]] == ["unscoped"]
    services.list_tasks.assert_awaited_once_with(
        user_id="admin",
        is_superuser=True,
        status=None,
        limit=50,
    )


def test_task_detail_and_cancel_routes_have_single_canonical_handler() -> None:
    app = FastAPI()
    app.include_router(tasks_router_mod.router)
    app.include_router(router_mod.router)

    route_keys = [
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", set())
        if route.path in {"/api/v1/tasks/{task_id}", "/api/v1/tasks/{task_id}/cancel"}
    ]

    assert route_keys.count(("GET", "/api/v1/tasks/{task_id}")) == 1
    assert route_keys.count(("POST", "/api/v1/tasks/{task_id}/cancel")) == 1

    schema = app.openapi()
    detail_schema = schema["paths"]["/api/v1/tasks/{task_id}"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    assert detail_schema["$ref"].endswith("/TaskLogResponse")
