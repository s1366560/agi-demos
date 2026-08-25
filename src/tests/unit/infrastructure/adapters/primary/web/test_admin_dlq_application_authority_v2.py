"""Request-lifetime coverage for the generation-owned admin DLQ authority."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.primary.web import admin_dlq_application_authority_v2 as subject
from src.infrastructure.adapters.primary.web.admin_dlq_application_authority_v2 import (
    AdminDlqApplicationAuthorityV2,
    admin_dlq_application_authority_context_v2,
)
from src.infrastructure.adapters.primary.web.routers.admin_dlq import require_admin
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.messaging.redis_dlq import RedisDLQAdapter
from src.infrastructure.adapters.secondary.persistence.models import User as DBUser
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2, RuntimeV2Error

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[7]
_ROUTER_PATH = _ROOT / "src/infrastructure/adapters/primary/web/routers/admin_dlq.py"


def _request(*, path: str, route_template: str, method: str = "GET") -> Request:
    return Request(
        {
            "type": "http",
            "app": FastAPI(),
            "headers": [],
            "method": method,
            "path": path,
            "path_params": {},
            "query_string": b"",
            "route": SimpleNamespace(path=route_template),
            "scheme": "http",
            "server": ("test", 80),
        }
    )


async def test_authority_pins_root_generation_and_disposes_after_handler() -> None:
    app = FastAPI()
    redis_client = object()
    host = await initialize_plugin_runtime_v2(app, sandbox_redis_client=redis_client)
    request = _request(
        path="/api/v1/admin/dlq/messages/dlq-secret/retry",
        route_template="/api/v1/admin/dlq/messages/{message_id}/retry",
        method="POST",
    )
    user = cast(DBUser, SimpleNamespace(id="admin-a", is_superuser=True, roles=[]))
    authority: AdminDlqApplicationAuthorityV2 | None = None
    try:
        async with (
            pin_generation_v2(host),
            admin_dlq_application_authority_context_v2(
                request=request,
                current_user=user,
            ) as authority,
        ):
            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 1
            assert authority.operation.context.scope.kind is ScopeKindV2.ROOT
            assert authority.current_user is user
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "user_id": "admin-a"
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "POST",
                "path": "/api/v1/admin/dlq/messages/{message_id}/retry",
            }
            assert isinstance(authority.services.queue, RedisDLQAdapter)
            assert "dlq-secret" not in authority.operation.operation_id
            assert "dlq-secret" not in str(
                authority.operation.require(OPERATION_METADATA_SERVICE_V2)
            )

        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        await host.close()


async def test_authority_propagates_unpinned_generation_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(
        path="/api/v1/admin/dlq/stats",
        route_template="/api/v1/admin/dlq/stats",
    )
    user = cast(DBUser, SimpleNamespace(id="admin-a", is_superuser=True, roles=[]))

    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(subject, "current_generation_v2", missing_generation)

    with pytest.raises(RuntimeV2Error) as error:
        async with admin_dlq_application_authority_context_v2(
            request=request,
            current_user=user,
        ):
            pass

    assert error.value.code == "generation_not_pinned"


async def test_authority_rejects_missing_application_service_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = FastAPI()
    host = await initialize_plugin_runtime_v2(app, sandbox_redis_client=object())
    request = _request(
        path="/api/v1/admin/dlq/messages",
        route_template="/api/v1/admin/dlq/messages",
    )
    user = cast(DBUser, SimpleNamespace(id="admin-a", is_superuser=True, roles=[]))
    monkeypatch.setattr(
        subject,
        "ADMIN_DLQ_APPLICATION_SERVICE_V2",
        "service:application/missing-admin-dlq-services",
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            async with (
                pin_generation_v2(host),
                admin_dlq_application_authority_context_v2(
                    request=request,
                    current_user=user,
                ),
            ):
                pass
    finally:
        await host.close()

    assert error.value.code == "missing_service"


def test_authority_dependency_owns_admin_access_and_router_has_no_static_fallback() -> None:
    non_admin = cast(
        DBUser,
        SimpleNamespace(
            id="user-a",
            is_superuser=False,
            roles=[SimpleNamespace(role=SimpleNamespace(name="user"))],
        ),
    )
    with pytest.raises(HTTPException) as error:
        require_admin(non_admin)
    assert error.value.status_code == 403

    source = _ROUTER_PATH.read_text(encoding="utf-8")
    assert "request.app.state.container" not in source
    assert "container.get(" not in source
    assert "get_dlq" not in source
    assert "DeadLetterQueuePort" not in source
    assert "admin_dlq_application_authority_dependency_v2" in source
