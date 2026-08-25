"""Request-lifetime coverage for the Billing V2 authority."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.primary.web.billing_application_authority_v2 import (
    BillingApplicationAuthorityV2,
    billing_application_authority_context_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import User as DBUser
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
_ROUTER_PATH = _ROOT / "src/infrastructure/adapters/primary/web/routers/billing.py"


def _request(*, path: str, route_template: str, method: str = "GET") -> Request:
    app = FastAPI()
    return Request(
        {
            "type": "http",
            "app": app,
            "headers": [],
            "method": method,
            "path": path,
            "path_params": {"tenant_id": "tenant-a"},
            "query_string": b"",
            "route": SimpleNamespace(path=route_template),
            "scheme": "http",
            "server": ("test", 80),
        }
    )


async def test_authority_pins_tenant_generation_and_disposes_after_handler() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=103,
        version=103,
    )
    request = _request(
        path="/api/v1/tenants/tenant-a/upgrade",
        route_template="/api/v1/tenants/{tenant_id}/upgrade",
        method="POST",
    )
    db = AsyncSession()
    user = cast(DBUser, SimpleNamespace(id="user-a", is_superuser=False))
    authority: BillingApplicationAuthorityV2 | None = None
    try:
        async with (
            pin_generation_v2(host),
            billing_application_authority_context_v2(
                request=request,
                current_user=user,
                db=db,
                tenant_id="tenant-a",
            ) as authority,
        ):
            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 103
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
                "method": "POST",
                "path": "/api/v1/tenants/{tenant_id}/upgrade",
            }
            assert authority.services.billing.persistence._session is db

        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        await db.close()
        await host.close()


async def test_authority_propagates_structured_generation_failure_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(
        path="/api/v1/tenants/tenant-a/billing",
        route_template="/api/v1/tenants/{tenant_id}/billing",
    )
    db = AsyncSession()
    user = cast(DBUser, SimpleNamespace(id="user-a", is_superuser=False))

    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.billing_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            async with billing_application_authority_context_v2(
                request=request,
                current_user=user,
                db=db,
                tenant_id="tenant-a",
            ):
                pass
    finally:
        await db.close()

    assert error.value.code == "generation_not_pinned"


def test_router_has_no_static_billing_persistence_or_policy_fallback() -> None:
    source = _ROUTER_PATH.read_text(encoding="utf-8")

    assert "_require_billing_role" not in source
    assert "_get_billing_tenant_or_404" not in source
    assert "PLAN_STORAGE_LIMITS" not in source
    assert "refresh_select_statement" not in source
    assert "get_current_user" not in source
    assert "get_db" not in source
    assert "sqlalchemy" not in source
    assert "select(" not in source
