"""V2 Provider/Consumer coverage for memory application composition."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.ports.services.graph_store_port import GraphStorePort
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.graph_application_services import GRAPH_APPLICATION_MODULE_V2
from src.infrastructure.plugins.v2.memory_services import (
    MEMORY_APPLICATION_MODULE_V2,
    MEMORY_APPLICATION_SERVICE_V2,
    MEMORY_REPOSITORY_PROVIDER_MODULE_V2,
    MEMORY_REPOSITORY_PROVIDER_SERVICE_V2,
    MemoryApplicationResolverV2,
    SqlMemoryRepositoryProviderV2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.retrieval_runtime import RETRIEVAL_RUNTIME_MODULE_V2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def _graph_factory() -> GraphStorePort:
    return cast(GraphStorePort, object())


async def test_memory_provider_builds_request_session_owned_repository() -> None:
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(graph_runtime_factory=_graph_factory)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=11,
        version=11,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="memory-provider:project-a",
                scope=ScopeV2(
                    kind=ScopeKindV2.PROJECT,
                    tenant_id="tenant-a",
                    project_id="project-a",
                ),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            provider = operation.require(MEMORY_REPOSITORY_PROVIDER_SERVICE_V2)

            assert isinstance(provider, SqlMemoryRepositoryProviderV2)
            repository = provider.build(operation)
            assert getattr(repository, "_session", None) is db
    finally:
        await db.close()
        await host.close()


async def test_memory_application_resolver_builds_complete_service_set() -> None:
    graph_service = cast(GraphStorePort, object())

    async def graph_factory() -> GraphStorePort:
        return graph_service

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(graph_runtime_factory=graph_factory)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=12,
        version=12,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="memory-application:project-a",
                scope=ScopeV2(
                    kind=ScopeKindV2.PROJECT,
                    tenant_id="tenant-a",
                    project_id="project-a",
                ),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(MEMORY_APPLICATION_SERVICE_V2)

            assert isinstance(resolver, MemoryApplicationResolverV2)
            services = resolver.resolve(operation)

            assert getattr(services.memory_repository, "_session", None) is db
            assert services.memory_service._memory_repo is services.memory_repository
            assert services.memory_service._graph_service is graph_service
            assert services.search_service._memory_repo is services.memory_repository
            assert services.search_service._graph_service is graph_service
            assert services.create_memory_use_case._memory_repo is services.memory_repository
            assert services.create_memory_use_case._graph_service is graph_service
            assert services.get_memory_use_case._memory_repo is services.memory_repository
            assert services.list_memories_use_case._memory_repo is services.memory_repository
            assert services.delete_memory_use_case._memory_repo is services.memory_repository
            assert services.delete_memory_use_case._graph_service is graph_service
            assert services.search_memory_use_case._graph_service is graph_service
    finally:
        await db.close()
        await host.close()


@pytest.mark.parametrize(
    ("disabled_module", "missing_service"),
    (
        (
            MEMORY_REPOSITORY_PROVIDER_MODULE_V2,
            "service:persistence.memory-repository-provider@1.0.0",
        ),
        ("builtin://memstack/graph/runtime", "service:graph.runtime@1.0.0"),
    ),
)
async def test_memory_application_rejects_missing_required_inject_without_fallback(
    disabled_module: str,
    missing_service: str,
) -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled_modules = {disabled_module}
    if disabled_module == "builtin://memstack/graph/runtime":
        disabled_modules.update(
            {
                GRAPH_APPLICATION_MODULE_V2,
                RETRIEVAL_RUNTIME_MODULE_V2,
            }
        )
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False) if entry.module_ref in disabled_modules else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=13)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2(graph_runtime_factory=_graph_factory)).stage(
            snapshot
        )

    assert error.value.code == "missing_inject_provider"
    assert "builtin-memory-services" in str(error.value)
    assert missing_service in str(error.value)


async def test_memory_application_propagates_unavailable_graph_without_builtin_fallback() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=14,
        version=14,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="memory-application:no-graph",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(MEMORY_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, MemoryApplicationResolverV2)

            with pytest.raises(RuntimeV2Error) as error:
                resolver.resolve(operation)

            assert error.value.code == "graph_runtime_factory_unavailable"
    finally:
        await db.close()
        await host.close()


def test_memory_modules_are_explicit_ordered_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert MEMORY_REPOSITORY_PROVIDER_MODULE_V2 in enabled_modules
    assert MEMORY_APPLICATION_MODULE_V2 in enabled_modules
    provider_index = enabled_modules.index(MEMORY_REPOSITORY_PROVIDER_MODULE_V2)
    assert provider_index < enabled_modules.index(MEMORY_APPLICATION_MODULE_V2)
