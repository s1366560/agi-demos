"""Request and operation coverage for sandbox application V2 authority."""

from __future__ import annotations

from collections.abc import AsyncIterator
from inspect import getsource, signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.sandbox_application_authority_v2 import (
    _connection_scope_v2,
    sandbox_application_authority_dependency_v2,
    sandbox_application_proxy_authority_dependency_v2,
    sandbox_application_websocket_authority_dependency_v2,
    sandbox_operation_authority_v2,
)
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter
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


class _RedisClient:
    async def scan_iter(self, *, match: str, count: int) -> AsyncIterator[str]:
        for key in ():
            yield key

    async def delete(self, *_keys: str | bytes) -> int:
        return 0

    async def aclose(self) -> None:
        return None

    async def xadd(self, _stream: str, _fields: dict[str, object], **_options: object) -> bytes:
        return b"1-0"


class _TrackedSandboxAdapter(MCPSandboxAdapter):
    def __init__(self) -> None:
        self.close_calls = 0

    async def sync_from_docker(self) -> int:
        return 0

    async def close(self) -> None:
        self.close_calls += 1


async def test_operation_authority_uses_exact_generation_scope_and_db() -> None:
    adapter = _TrackedSandboxAdapter()
    redis_client = _RedisClient()
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(
            sandbox_runtime_factory=lambda: adapter,
            sandbox_redis_client=redis_client,
        )
    )
    publication = await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=82,
        version=82,
    )
    assert publication.accepted is True
    db = AsyncSession()
    authority = None
    try:
        async with (
            pin_generation_v2(host),
            sandbox_operation_authority_v2(
                db=db,
                operation_id="sandbox-authority:test",
                scope=ScopeV2(
                    kind=ScopeKindV2.PROJECT,
                    tenant_id="tenant-a",
                    project_id="project-a",
                ),
                identity={"tenant_id": "tenant-a", "user_id": "user-a"},
                metadata={"kind": "test"},
            ) as authority,
        ):
            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 82
            assert authority.operation.context.scope.kind is ScopeKindV2.PROJECT
            assert authority.operation.context.scope.tenant_id == "tenant-a"
            assert authority.operation.context.scope.project_id == "project-a"
            assert authority.db is db
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {"kind": "test"}
            assert authority.services.lifecycle_service._adapter is adapter
            assert authority.services.lifecycle_service._repository._session is db
            assert authority.services.lifecycle_service._distributed_lock._redis is redis_client

        assert authority is not None
        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        await db.close()
        await host.close()

    assert adapter.close_calls == 1


async def test_operation_authority_fails_closed_without_a_pinned_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = AsyncSession()

    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.sandbox_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    authority = sandbox_operation_authority_v2(
        db=db,
        operation_id="sandbox-authority:missing",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
        identity={"user_id": "user-a"},
        metadata={"kind": "test"},
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            await authority.__aenter__()
    finally:
        await authority.__aexit__(None, None, None)
        await db.close()

    assert error.value.code == "generation_not_pinned"


async def test_connection_scope_uses_persisted_project_tenant() -> None:
    result = SimpleNamespace(scalar_one_or_none=lambda: "tenant-a")
    db = cast(AsyncSession, SimpleNamespace(execute=AsyncMock(return_value=result)))
    request = cast(
        Any,
        SimpleNamespace(
            path_params={"project_id": "project-a"},
            query_params={},
        ),
    )

    scope = await _connection_scope_v2(request=request, db=db)

    assert scope == ScopeV2(
        kind=ScopeKindV2.PROJECT,
        tenant_id="tenant-a",
        project_id="project-a",
    )
    db.execute.assert_awaited_once()


async def test_connection_scope_rejects_tenant_project_mismatch() -> None:
    result = SimpleNamespace(scalar_one_or_none=lambda: "tenant-persisted")
    db = cast(AsyncSession, SimpleNamespace(execute=AsyncMock(return_value=result)))
    request = cast(
        Any,
        SimpleNamespace(
            path_params={"project_id": "project-a"},
            query_params={"tenant_id": "tenant-requested"},
        ),
    )

    with pytest.raises(RuntimeV2Error) as error:
        await _connection_scope_v2(request=request, db=db)

    assert error.value.code == "sandbox_operation_scope_mismatch"


async def test_connection_scope_rejects_unknown_project() -> None:
    result = SimpleNamespace(scalar_one_or_none=lambda: None)
    db = cast(AsyncSession, SimpleNamespace(execute=AsyncMock(return_value=result)))
    request = cast(
        Any,
        SimpleNamespace(
            path_params={"project_id": "missing-project"},
            query_params={"tenant_id": "tenant-requested"},
        ),
    )

    with pytest.raises(RuntimeV2Error) as error:
        await _connection_scope_v2(request=request, db=db)

    assert error.value.code == "sandbox_operation_project_not_found"


def test_project_sandbox_http_and_websocket_dependencies_use_v2_authority() -> None:
    from src.infrastructure.adapters.primary.web.routers import project_sandbox

    http_parameter = signature(project_sandbox.get_lifecycle_service).parameters["authority"]
    websocket_parameter = signature(project_sandbox.get_lifecycle_service_for_websocket).parameters[
        "authority"
    ]
    proxy_parameter = signature(project_sandbox.get_lifecycle_service_for_proxy).parameters[
        "authority"
    ]

    assert http_parameter.default.dependency is sandbox_application_authority_dependency_v2
    assert (
        websocket_parameter.default.dependency
        is sandbox_application_websocket_authority_dependency_v2
    )
    assert proxy_parameter.default.dependency is sandbox_application_proxy_authority_dependency_v2
    assert "request" not in signature(project_sandbox.get_lifecycle_service).parameters
    assert "db" not in signature(project_sandbox.get_lifecycle_service).parameters
    assert (
        "websocket" not in signature(project_sandbox.get_lifecycle_service_for_websocket).parameters
    )
    assert (
        signature(project_sandbox.proxy_project_desktop).parameters["service"].default.dependency
        is project_sandbox.get_lifecycle_service_for_proxy
    )


def test_legacy_create_and_background_callers_use_v2_operation_authority() -> None:
    from src.infrastructure.adapters.primary.web.routers.agent import plans
    from src.infrastructure.adapters.primary.web.routers.sandbox import lifecycle
    from src.infrastructure.adapters.primary.web.websocket.handlers import lifecycle_handler

    create_source = getsource(lifecycle.create_sandbox)
    assert "sandbox_operation_authority_v2" in create_source
    assert "sandbox_authority" not in signature(lifecycle.create_sandbox).parameters
    assert "base_container" not in signature(plans._resolve_cloud_run_environment).parameters
    for function in (
        lifecycle_handler._ensure_sandbox_exists,
        lifecycle_handler._sync_and_repair_sandbox,
        plans._resolve_cloud_run_environment,
    ):
        source = getsource(function)
        assert "sandbox_operation_authority_v2" in source
        assert "project_sandbox_lifecycle_service" not in source


def test_lifecycle_di_accessors_and_binding_are_retired() -> None:
    from src.configuration.di_container import DIContainer

    assert "project_sandbox_lifecycle_service" not in vars(DIContainer)
