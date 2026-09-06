"""V2 Provider/Consumer coverage for MCP application composition."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.mcp_services import (
    MCP_APPLICATION_MODULE_V2,
    MCP_APPLICATION_SERVICE_V2,
    MCP_OPERATION_PROVIDER_MODULE_V2,
    MCP_OPERATION_PROVIDER_SERVICE_V2,
    MCPApplicationResolverV2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


class _TrackedSandboxAdapter(MCPSandboxAdapter):
    def __init__(self) -> None:
        self.close_calls = 0

    async def sync_from_docker(self) -> int:
        return 0

    async def close(self) -> None:
        self.close_calls += 1


class _RedisCacheClient:
    async def scan_iter(self, *, match: str, count: int) -> AsyncIterator[str | bytes]:
        for key in ():
            yield key

    async def delete(self, *keys: str | bytes) -> int:
        return 0

    async def xadd(self, *_args: object, **_kwargs: object) -> object:
        raise AssertionError("Redis stream publication is outside this authority fixture")


async def test_mcp_application_resolver_builds_one_operation_owned_service_graph() -> None:
    adapter = _TrackedSandboxAdapter()
    redis_client = _RedisCacheClient()
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(
            sandbox_runtime_factory=lambda: adapter,
            sandbox_redis_client=redis_client,
        )
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=91,
        version=91,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="mcp-application:tenant-a",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(MCP_APPLICATION_SERVICE_V2)

            assert isinstance(resolver, MCPApplicationResolverV2)
            services = resolver.resolve(operation)

            assert services.sandbox_manager._sandbox_resource is not None
            assert services.sandbox_manager._app_service is services.app_service
            assert (
                services.app_service._resource_resolver._get_manager() is services.sandbox_manager
            )
            assert services.runtime_service._sandbox_manager is services.sandbox_manager
            assert services.runtime_service._app_service is services.app_service
            assert services.runtime_service._redis_client is redis_client
            assert services.app_service._app_repo._session is db
            assert services.runtime_service._server_repo._session is db
            assert services.runtime_service._app_repo._session is db
            assert services.runtime_service._lifecycle_event_repo._db is db
            assert services.runtime_service._project_repo._session is db
    finally:
        await db.close()
        await host.close()

    assert adapter.close_calls == 1


async def test_mcp_application_rejects_missing_provider_without_static_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == MCP_OPERATION_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=92)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert MCP_OPERATION_PROVIDER_SERVICE_V2 in str(error.value)


def test_mcp_modules_are_explicit_ordered_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert MCP_OPERATION_PROVIDER_MODULE_V2 in enabled_modules
    assert MCP_APPLICATION_MODULE_V2 in enabled_modules
    assert enabled_modules.index(MCP_OPERATION_PROVIDER_MODULE_V2) < enabled_modules.index(
        MCP_APPLICATION_MODULE_V2
    )
