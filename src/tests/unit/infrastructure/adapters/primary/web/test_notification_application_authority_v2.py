"""Request authority and handler coverage for the notification V2 surface."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.primary.web.notification_application_authority_v2 import (
    NotificationApplicationAuthorityV2,
    notification_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import notifications
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.notification_services import NotificationNotFoundV2
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
            "path": "/api/v1/notifications/",
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
        generation=26,
        version=26,
    )
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a"))
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = notification_application_authority_dependency_v2(
                request=_request(),
                current_user=user,
                db=db,
            )
            authority = await anext(dependency)

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 26
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
                "path": "/api/v1/notifications/",
            }
            assert getattr(authority.services.persistence, "_session", None) is db
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
        "src.infrastructure.adapters.primary.web.notification_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    db = AsyncSession()
    dependency = notification_application_authority_dependency_v2(
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


@pytest.mark.parametrize(
    "handler",
    (
        notifications.list_notifications,
        notifications.mark_notification_read,
        notifications.mark_all_read,
        notifications.delete_notification,
        notifications.create_notification,
    ),
)
def test_notification_handlers_require_only_the_v2_application_authority(handler: object) -> None:
    parameters = signature(handler).parameters
    parameter = parameters["notification_application"]

    assert parameter.default.dependency is notification_application_authority_dependency_v2
    assert parameter.annotation in {
        "NotificationApplicationAuthorityV2",
        NotificationApplicationAuthorityV2,
    }
    assert "db" not in parameters


def test_notification_router_removes_static_sql_dependencies() -> None:
    assert "get_db" not in vars(notifications)
    assert "select" not in vars(notifications)
    assert "update" not in vars(notifications)
    assert "Notification" not in vars(notifications)


async def test_list_notifications_delegates_identity_and_filters_to_v2_service() -> None:
    services = SimpleNamespace(list_notifications=AsyncMock(return_value=[]))

    result = await notifications.list_notifications(
        unread_only=True,
        limit=7,
        current_user=cast(User, SimpleNamespace(id="user-a")),
        notification_application=SimpleNamespace(services=services),
    )

    assert result == {"notifications": []}
    services.list_notifications.assert_awaited_once_with(
        user_id="user-a",
        unread_only=True,
        limit=7,
    )


async def test_mark_read_translates_typed_not_found_without_db_fallback() -> None:
    services = SimpleNamespace(
        mark_notification_read=AsyncMock(side_effect=NotificationNotFoundV2())
    )

    with pytest.raises(HTTPException) as error:
        await notifications.mark_notification_read(
            notification_id="missing",
            current_user=cast(User, SimpleNamespace(id="user-a")),
            notification_application=SimpleNamespace(services=services),
        )

    assert error.value.status_code == 404
    assert error.value.detail == "Notification not found"
