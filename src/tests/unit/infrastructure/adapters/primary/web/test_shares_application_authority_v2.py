"""Request-lifetime coverage for the memory Shares V2 authority."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.primary.web import shares_application_authority_v2 as subject
from src.infrastructure.adapters.primary.web.shares_application_authority_v2 import (
    SharesApplicationAuthorityV2,
    shares_application_authority_context_v2,
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
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_ROUTER_PATH = _ROOT / "src/infrastructure/adapters/primary/web/routers/shares.py"


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


async def _host(*, generation: int) -> PlatformPluginRuntimeHostV2:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=generation,
        version=generation,
    )
    assert publication.accepted is True
    return host


async def test_authenticated_authority_pins_root_generation_and_disposes_after_handler() -> None:
    host = await _host(generation=108)
    request = _request(
        path="/api/v1/memories/memory-a/shares",
        route_template="/api/v1/memories/{memory_id}/shares",
        method="POST",
    )
    db = AsyncSession()
    user = cast(DBUser, SimpleNamespace(id="user-a", is_superuser=False))
    authority: SharesApplicationAuthorityV2 | None = None
    try:
        async with (
            pin_generation_v2(host),
            shares_application_authority_context_v2(
                request=request,
                current_user=user,
                db=db,
            ) as authority,
        ):
            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 108
            assert authority.operation.context.scope.kind is ScopeKindV2.ROOT
            assert authority.operation.context.scope.tenant_id is None
            assert authority.operation.context.scope.project_id is None
            assert authority.db is db
            assert authority.current_user is user
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "user_id": "user-a"
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "POST",
                "path": "/api/v1/memories/{memory_id}/shares",
            }
            assert authority.services.shares.persistence._session is db

        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        await db.close()
        await host.close()


async def test_public_authority_is_anonymous_root_scoped_and_redacts_share_token() -> None:
    host = await _host(generation=109)
    secret = "bearer-equivalent-share-token"
    request = _request(
        path=f"/api/v1/shared/{secret}",
        route_template="/api/v1/shared/{share_token}",
    )
    db = AsyncSession()
    try:
        async with (
            pin_generation_v2(host),
            shares_application_authority_context_v2(
                request=request,
                current_user=None,
                db=db,
            ) as authority,
        ):
            assert authority.operation.context.scope.kind is ScopeKindV2.ROOT
            assert authority.current_user is None
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {}
            metadata = authority.operation.require(OPERATION_METADATA_SERVICE_V2)
            assert metadata == {
                "kind": "http-authority",
                "method": "GET",
                "path": "/api/v1/shared/{share_token}",
            }
            assert secret not in str(metadata)
            assert secret not in authority.operation.operation_id
            assert authority.services.shares.persistence._session is db
    finally:
        await db.close()
        await host.close()


async def test_authority_propagates_structured_generation_failure_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(
        path="/api/v1/memories/memory-a/shares",
        route_template="/api/v1/memories/{memory_id}/shares",
    )
    db = AsyncSession()
    user = cast(DBUser, SimpleNamespace(id="user-a", is_superuser=False))

    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(subject, "current_generation_v2", missing_generation)
    try:
        with pytest.raises(RuntimeV2Error) as error:
            async with shares_application_authority_context_v2(
                request=request,
                current_user=user,
                db=db,
            ):
                pass
    finally:
        await db.close()

    assert error.value.code == "generation_not_pinned"


async def test_authority_rejects_missing_application_service_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    host = await _host(generation=110)
    request = _request(
        path="/api/v1/shared/share-token",
        route_template="/api/v1/shared/{share_token}",
    )
    db = AsyncSession()
    monkeypatch.setattr(
        subject,
        "SHARES_APPLICATION_SERVICE_V2",
        "service:application/missing-shares-services",
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            async with (
                pin_generation_v2(host),
                shares_application_authority_context_v2(
                    request=request,
                    current_user=None,
                    db=db,
                ),
            ):
                pass
    finally:
        await db.close()
        await host.close()

    assert error.value.code == "missing_service"


async def test_authority_does_not_own_commit_or_rollback_transport_boundary() -> None:
    host = await _host(generation=111)
    request = _request(
        path="/api/v1/memories/memory-a/shares/share-a",
        route_template="/api/v1/memories/{memory_id}/shares/{share_id}",
        method="DELETE",
    )
    db = AsyncMock(spec=AsyncSession)
    user = cast(DBUser, SimpleNamespace(id="user-a", is_superuser=False))

    class HandlerFailure(Exception):
        pass

    try:
        with pytest.raises(HandlerFailure):
            async with (
                pin_generation_v2(host),
                shares_application_authority_context_v2(
                    request=request,
                    current_user=user,
                    db=db,
                ) as authority,
            ):
                assert authority.db is db
                raise HandlerFailure
    finally:
        await host.close()

    db.commit.assert_not_awaited()
    db.rollback.assert_not_awaited()


def test_router_has_no_static_share_persistence_or_policy_fallback() -> None:
    source = _ROUTER_PATH.read_text(encoding="utf-8")

    assert "_check_project_admin_access" not in source
    assert "_ensure_share_target_authorized" not in source
    assert "_find_existing_target_share" not in source
    assert "_parse_share_expiration" not in source
    assert "_new_share_token" not in source
    assert "_share_can_view" not in source
    assert "refresh_select_statement" not in source
    assert "MemoryShare" not in source
    assert "get_current_user" not in source
    assert "get_db" not in source
    assert "sqlalchemy" not in source
    assert "select(" not in source
