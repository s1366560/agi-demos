"""Request-lifetime coverage for the tenant webhook V2 authority."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.domain.model.auth.user import User
from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.primary.web.tenant_webhook_application_authority_v2 import (
    TenantWebhookApplicationAuthorityV2,
    tenant_webhook_application_authority_context_v2,
)
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
_ROUTER_PATH = _ROOT / "src/infrastructure/adapters/primary/web/routers/tenant_webhooks.py"


def _request() -> Request:
    app = FastAPI()
    return Request(
        {
            "type": "http",
            "app": app,
            "headers": [],
            "method": "GET",
            "path": "/api/v1/tenant-webhooks/tenant-a",
            "path_params": {"tenant_id": "tenant-a"},
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


async def test_authority_pins_tenant_generation_and_disposes_after_handler() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=68,
        version=68,
    )
    request = _request()
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a", is_superuser=False))
    authority: TenantWebhookApplicationAuthorityV2 | None = None
    try:
        async with (
            pin_generation_v2(host),
            tenant_webhook_application_authority_context_v2(
                request=request,
                current_user=user,
                db=db,
                tenant_id="tenant-a",
            ) as authority,
        ):
            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 68
            assert authority.operation.context.scope.kind is ScopeKindV2.TENANT
            assert authority.operation.context.scope.tenant_id == "tenant-a"
            assert authority.db is db
            assert authority.current_user is user
            assert authority.tenant_id == "tenant-a"
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "GET",
                "path": "/api/v1/tenant-webhooks/tenant-a",
            }
            assert authority.services.webhooks._webhook_repo._session is db

        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        await db.close()
        await host.close()


async def test_authority_uses_root_scope_when_target_tenant_is_not_known_yet() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=69,
        version=69,
    )
    request = _request()
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a", is_superuser=False))
    try:
        async with (
            pin_generation_v2(host),
            tenant_webhook_application_authority_context_v2(
                request=request,
                current_user=user,
                db=db,
                tenant_id=None,
            ) as authority,
        ):
            assert authority.operation.context.scope.kind is ScopeKindV2.ROOT
            assert authority.operation.context.scope.tenant_id is None
            assert authority.tenant_id is None
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "user_id": "user-a"
            }
    finally:
        await db.close()
        await host.close()


async def test_authority_propagates_structured_generation_failure_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a", is_superuser=False))

    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.tenant_webhook_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            async with tenant_webhook_application_authority_context_v2(
                request=request,
                current_user=user,
                db=db,
                tenant_id="tenant-a",
            ):
                pass
    finally:
        await db.close()

    assert error.value.code == "generation_not_pinned"


def test_router_has_no_static_webhook_authority_fallback() -> None:
    source = _ROUTER_PATH.read_text(encoding="utf-8")

    assert "DIContainer" not in source
    assert "get_container_with_db" not in source
    assert "app.state.container" not in source
    assert ".webhook_service()" not in source
