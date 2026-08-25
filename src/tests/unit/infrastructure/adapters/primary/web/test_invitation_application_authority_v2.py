"""Request-lifetime coverage for the invitation V2 authority."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.primary.web.invitation_application_authority_v2 import (
    InvitationApplicationAuthorityV2,
    invitation_application_authority_context_v2,
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
_ROUTER_PATH = _ROOT / "src/infrastructure/adapters/primary/web/routers/invitations.py"


def _request(*, path: str, route_template: str, method: str = "GET") -> Request:
    app = FastAPI()
    return Request(
        {
            "type": "http",
            "app": app,
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


async def test_authority_pins_tenant_generation_and_disposes_after_handler() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=74,
        version=74,
    )
    request = _request(
        path="/api/v1/tenants/tenant-a/invitations",
        route_template="/api/v1/tenants/{tenant_id}/invitations",
        method="POST",
    )
    db = AsyncSession()
    user = cast(DBUser, SimpleNamespace(id="user-a", is_superuser=False))
    authority: InvitationApplicationAuthorityV2 | None = None
    try:
        async with (
            pin_generation_v2(host),
            invitation_application_authority_context_v2(
                request=request,
                current_user=user,
                db=db,
                tenant_id="tenant-a",
            ) as authority,
        ):
            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 74
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
                "path": "/api/v1/tenants/{tenant_id}/invitations",
            }
            assert authority.services.invitations._repo._session is db
            assert authority.services.memberships.db is db

        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        await db.close()
        await host.close()


async def test_public_authority_is_anonymous_root_scoped_and_redacts_token() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=75,
        version=75,
    )
    secret = "secret-invitation-token"
    request = _request(
        path=f"/api/v1/invitations/verify/{secret}",
        route_template="/api/v1/invitations/verify/{token}",
    )
    db = AsyncSession()
    try:
        async with (
            pin_generation_v2(host),
            invitation_application_authority_context_v2(
                request=request,
                current_user=None,
                db=db,
                tenant_id=None,
            ) as authority,
        ):
            assert authority.operation.context.scope.kind is ScopeKindV2.ROOT
            assert authority.operation.context.scope.tenant_id is None
            assert authority.current_user is None
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {}
            metadata = authority.operation.require(OPERATION_METADATA_SERVICE_V2)
            assert metadata["path"] == "/api/v1/invitations/verify/{token}"
            assert secret not in str(metadata)
            assert secret not in authority.operation.operation_id
    finally:
        await db.close()
        await host.close()


async def test_public_accept_authority_keeps_user_identity_at_root_scope() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=80,
        version=80,
    )
    secret = "secret-accept-token"
    request = _request(
        path=f"/api/v1/invitations/accept/{secret}",
        route_template="/api/v1/invitations/accept/{token}",
        method="POST",
    )
    db = AsyncSession()
    user = cast(DBUser, SimpleNamespace(id="user-a", is_superuser=False))
    try:
        async with (
            pin_generation_v2(host),
            invitation_application_authority_context_v2(
                request=request,
                current_user=user,
                db=db,
                tenant_id=None,
            ) as authority,
        ):
            assert authority.operation.context.scope.kind is ScopeKindV2.ROOT
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "user_id": "user-a"
            }
            metadata = authority.operation.require(OPERATION_METADATA_SERVICE_V2)
            assert metadata["path"] == "/api/v1/invitations/accept/{token}"
            assert secret not in str(metadata)
    finally:
        await db.close()
        await host.close()


async def test_authority_propagates_structured_generation_failure_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(
        path="/api/v1/tenants/tenant-a/invitations",
        route_template="/api/v1/tenants/{tenant_id}/invitations",
    )
    db = AsyncSession()
    user = cast(DBUser, SimpleNamespace(id="user-a", is_superuser=False))

    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.invitation_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            async with invitation_application_authority_context_v2(
                request=request,
                current_user=user,
                db=db,
                tenant_id="tenant-a",
            ):
                pass
    finally:
        await db.close()

    assert error.value.code == "generation_not_pinned"


def test_router_has_no_static_invitation_authority_fallback() -> None:
    source = _ROUTER_PATH.read_text(encoding="utf-8")

    assert "_build_service" not in source
    assert "InvitationService" not in source
    assert "SqlInvitationRepository" not in source
    assert "refresh_select_statement" not in source
    assert "UserTenant" not in source
    assert "select(" not in source
