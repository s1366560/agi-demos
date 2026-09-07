"""Request-lifetime coverage for the tenant agent config V2 authority."""

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
from src.infrastructure.adapters.primary.web.tenant_agent_config_application_authority_v2 import (
    TenantAgentConfigApplicationAuthorityV2,
    tenant_agent_config_application_authority_context_v2,
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
_ROUTER_PATH = _ROOT / "src/infrastructure/adapters/primary/web/routers/agent/config.py"


def _request() -> Request:
    app = FastAPI()
    return Request(
        {
            "type": "http",
            "app": app,
            "headers": [],
            "method": "GET",
            "path": "/api/v1/agent/config",
            "path_params": {},
            "query_string": b"tenant_id=tenant-a",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


async def test_authority_pins_tenant_generation_and_disposes_after_handler() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=74,
        version=74,
    )
    request = _request()
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a", is_superuser=False))
    authority: TenantAgentConfigApplicationAuthorityV2 | None = None
    try:
        async with (
            pin_generation_v2(host),
            tenant_agent_config_application_authority_context_v2(
                request=request,
                current_user=user,
                tenant_id="tenant-a",
                db=db,
            ) as current,
        ):
            authority = current
            assert current.operation.phase is FiberPhaseV2.ACTIVE
            assert current.operation.descriptor.generation == 74
            assert current.operation.context.scope.kind is ScopeKindV2.TENANT
            assert current.operation.context.scope.tenant_id == "tenant-a"
            assert current.db is db
            assert current.current_user is user
            assert current.tenant_id == "tenant-a"
            assert current.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert current.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
            }
            assert current.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "GET",
                "path": "/api/v1/agent/config",
            }
            assert current.services.configs._session is db
            assert current.services.authority._session is db

        assert authority is not None
        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        await db.close()
        await host.close()


async def test_authority_propagates_generation_failure_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a", is_superuser=False))

    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web."
        "tenant_agent_config_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            async with tenant_agent_config_application_authority_context_v2(
                request=request,
                current_user=user,
                tenant_id="tenant-a",
                db=db,
            ):
                raise AssertionError("authority should not be yielded")
    finally:
        await db.close()

    assert error.value.code == "generation_not_pinned"


def test_router_has_no_static_tenant_agent_config_authority_fallback() -> None:
    source = _ROUTER_PATH.read_text(encoding="utf-8")

    assert "SqlTenantAgentConfigRepository" not in source
    assert "SqlTenantAgentConfigAuthorityRepository" not in source
    assert "tenant_agent_config_repository" not in source
    assert "using defaults instead" not in source
