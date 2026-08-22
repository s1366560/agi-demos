"""Request authority and handler coverage for the background-task V2 surface."""

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

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.primary.web.background_task_application_authority_v2 import (
    BackgroundTaskApplicationAuthorityV2,
    background_task_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import background_tasks
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.background_task_services import BackgroundTaskPageV2
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
            "method": "GET",
            "path": "/api/v1/tasks/",
            "path_params": {},
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
        generation=65,
        version=65,
    )
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a", is_superuser=False))
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = background_task_application_authority_dependency_v2(
                request=_request(),
                current_user=user,
                db=db,
            )
            authority = await anext(dependency)

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 65
            assert authority.operation.context.scope.kind is ScopeKindV2.ROOT
            assert authority.db is db
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": None,
                "user_id": "user-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "GET",
                "path": "/api/v1/tasks/",
            }
            assert getattr(authority.services.access, "_session", None) is db
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
        "src.infrastructure.adapters.primary.web.background_task_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    db = AsyncSession()
    dependency = background_task_application_authority_dependency_v2(
        request=_request(),
        current_user=cast(User, SimpleNamespace(id="user-a", is_superuser=False)),
        db=db,
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            await anext(dependency)
    finally:
        await dependency.aclose()
        await db.close()

    assert error.value.code == "generation_not_pinned"


def test_background_task_handler_requires_only_v2_application_authority() -> None:
    parameters = signature(background_tasks.list_tasks).parameters
    parameter = parameters["background_task_application"]

    assert parameter.default.dependency is background_task_application_authority_dependency_v2
    assert parameter.annotation in {
        "BackgroundTaskApplicationAuthorityV2",
        BackgroundTaskApplicationAuthorityV2,
    }
    assert "db" not in parameters


def test_background_task_router_removes_static_manager_and_sql_dependencies() -> None:
    assert "task_manager" not in vars(background_tasks)
    assert "get_db" not in vars(background_tasks)
    assert "select" not in vars(background_tasks)
    assert "UserProject" not in vars(background_tasks)


async def test_list_tasks_delegates_identity_and_filters_to_v2_service() -> None:
    services = SimpleNamespace(
        list_tasks=AsyncMock(
            return_value=BackgroundTaskPageV2(
                tasks=({"task_id": "owned"},),
                total=1,
            )
        )
    )

    result = await background_tasks.list_tasks(
        status="running",
        limit=7,
        current_user=cast(User, SimpleNamespace(id="user-a", is_superuser=False)),
        background_task_application=SimpleNamespace(services=services),
    )

    assert result == {"tasks": [{"task_id": "owned"}], "total": 1}
    services.list_tasks.assert_awaited_once_with(
        user_id="user-a",
        is_superuser=False,
        status="running",
        limit=7,
    )
