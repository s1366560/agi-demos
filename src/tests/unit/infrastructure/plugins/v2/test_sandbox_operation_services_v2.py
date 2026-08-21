"""Operation-scoped Provider/Consumer coverage for sandbox application services."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import load_profile_document_v2
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.sandbox_operation_services import (
    SANDBOX_OPERATION_APPLICATION_MODULE_V2,
    SANDBOX_OPERATION_APPLICATION_SERVICE_V2,
    SandboxOperationApplicationResolverV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _TrackedSandboxAdapter(MCPSandboxAdapter):
    def __init__(self) -> None:
        self.sync_calls = 0
        self.close_calls = 0

    async def sync_from_docker(self) -> int:
        self.sync_calls += 1
        return 0

    async def close(self) -> None:
        self.close_calls += 1


async def test_operation_resolver_builds_services_from_exact_session() -> None:
    adapter = _TrackedSandboxAdapter()
    redis_client = object()
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(
            sandbox_runtime_factory=lambda: adapter,
            sandbox_redis_client=redis_client,
        )
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=79,
        version=79,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="sandbox-operation:project-a",
                scope=ScopeV2(
                    kind=ScopeKindV2.PROJECT,
                    tenant_id="tenant-a",
                    project_id="project-a",
                ),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(SANDBOX_OPERATION_APPLICATION_SERVICE_V2)

            assert isinstance(resolver, SandboxOperationApplicationResolverV2)
            services = resolver.resolve(operation)
            assert services.sandbox_resource._adapter is adapter
            assert services.lifecycle_service._adapter is adapter
            assert services.sandbox_resource._repository._session is db
            assert services.lifecycle_service._repository._session is db
            assert services.sandbox_resource._distributed_lock._redis is redis_client
            assert services.lifecycle_service._distributed_lock._redis is redis_client
    finally:
        await db.close()
        await host.close()

    assert adapter.close_calls == 1


async def test_operation_resolver_rejects_missing_db_without_fallback() -> None:
    adapter = _TrackedSandboxAdapter()
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(sandbox_runtime_factory=lambda: adapter)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=80,
        version=80,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="sandbox-operation:missing-db",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            resolver = operation.require(SANDBOX_OPERATION_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, SandboxOperationApplicationResolverV2)

            with pytest.raises(RuntimeV2Error) as error:
                resolver.resolve(operation)

            assert error.value.code == "missing_service"
    finally:
        await host.close()


async def test_operation_resolver_rejects_unavailable_runtime_without_fallback() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=81,
        version=81,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="sandbox-operation:unavailable",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(SANDBOX_OPERATION_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, SandboxOperationApplicationResolverV2)

            with pytest.raises(RuntimeV2Error) as error:
                resolver.resolve(operation)

            assert error.value.code == "sandbox_runtime_factory_unavailable"
    finally:
        await db.close()
        await host.close()


def test_operation_services_are_an_explicit_profile_entry() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    entry = next(
        item
        for item in document.entries
        if item.module_ref == SANDBOX_OPERATION_APPLICATION_MODULE_V2
    )

    assert entry.enabled is True
    assert entry.config == {"strategy": "operation-scoped-provider"}
    assert entry.inject == {
        "provider": "service:sandbox.operation-service-provider",
    }
