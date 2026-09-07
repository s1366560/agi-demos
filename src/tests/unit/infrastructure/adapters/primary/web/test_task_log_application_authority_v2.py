"""Request-lifetime coverage for the task-log application V2 authority."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.infrastructure.adapters.primary.web.routers import tasks
from src.infrastructure.adapters.primary.web.task_log_application_authority_v2 import (
    TaskLogApplicationAuthorityV2,
    task_log_application_authority_dependency_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[7]


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "app": FastAPI(),
            "headers": [],
            "method": "POST",
            "path": "/api/v1/tasks/task-a/stop",
            "path_params": {"task_id": "task-a"},
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


async def test_authority_uses_pinned_generation_and_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=156,
        version=156,
    )
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a"))
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = task_log_application_authority_dependency_v2(
                request=_request(),
                current_user=user,
                db=db,
            )
            authority = await anext(dependency)

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 156
            assert authority.db is db
            assert authority.services.get_task._task_repo._session is db
            assert authority.services.update_task._task_repo._session is db
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": None,
                "user_id": "user-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "POST",
                "path": "/api/v1/tasks/task-a/stop",
            }
            await dependency.aclose()

        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        if dependency is not None:
            await dependency.aclose()
        await db.close()
        await host.close()


async def test_authority_fails_closed_without_a_pinned_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.task_log_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    db = AsyncSession()
    dependency = task_log_application_authority_dependency_v2(
        request=_request(),
        current_user=cast(User, SimpleNamespace(id="user-a")),
        db=db,
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            await anext(dependency)
    finally:
        await dependency.aclose()
        await db.close()

    assert error.value.code == "generation_not_pinned"


def test_router_dependencies_resolve_only_from_v2_authority() -> None:
    for endpoint in (tasks.stop_task_endpoint, tasks.cancel_task_endpoint):
        parameter = signature(endpoint).parameters["task_log_application"]
        assert parameter.default.dependency is task_log_application_authority_dependency_v2
        assert parameter.annotation in {
            "TaskLogApplicationAuthorityV2",
            TaskLogApplicationAuthorityV2,
        }

    assert "get_di_container" not in vars(tasks)
    assert "DIContainer" not in vars(tasks)


async def test_stop_endpoint_executes_only_authority_owned_use_cases() -> None:
    get_task = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(id="task-a", status="PENDING"))
    )
    update_task = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(id="task-a")))
    authority = cast(
        TaskLogApplicationAuthorityV2,
        SimpleNamespace(services=SimpleNamespace(get_task=get_task, update_task=update_task)),
    )
    db = cast(AsyncSession, SimpleNamespace(commit=AsyncMock()))
    user = cast(User, SimpleNamespace(id="user-a", is_superuser=True))

    response = await tasks.stop_task_endpoint("task-a", user, db, authority)

    query = get_task.execute.await_args.args[0]
    command = update_task.execute.await_args.args[0]
    assert query.task_id == "task-a"
    assert command.task_id == "task-a"
    assert command.status == "FAILED"
    assert command.error_message == "Task stopped by user"
    assert response == {"message": "Task marked as stopped"}
    db.commit.assert_awaited_once_with()
