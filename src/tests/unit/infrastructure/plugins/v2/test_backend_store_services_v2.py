"""V2 provider and application coverage for graph/retrieval store composition."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.graph.registry import get_graph_backend_registry
from src.infrastructure.plugins.v2.backend_store_services import (
    BACKEND_STORE_APPLICATION_MODULE_V2,
    BACKEND_STORE_APPLICATION_SERVICE_V2,
    BACKEND_STORE_PROVIDER_MODULE_V2,
    BACKEND_STORE_PROVIDER_SERVICE_V2,
    BackendStoreApplicationResolverV2,
    SqlBackendStoreServiceFactoryV2,
)
from src.infrastructure.plugins.v2.boundary import OPERATION_DB_SESSION_SERVICE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.retrieval.registry import get_retrieval_backend_registry

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


@pytest.mark.unit
async def test_backend_store_provider_builds_request_session_owned_services() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=7,
        version=7,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="backend-store-provider:project-a",
                scope=ScopeV2(
                    kind=ScopeKindV2.PROJECT,
                    tenant_id="tenant-a",
                    project_id="project-a",
                ),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            provider = operation.require(BACKEND_STORE_PROVIDER_SERVICE_V2)
            assert isinstance(provider, SqlBackendStoreServiceFactoryV2)

            services = provider.build(operation)

            assert getattr(services.graph_service._repo, "_session", None) is db
            assert getattr(services.retrieval_service._repo, "_session", None) is db
            assert services.graph_service._registry is get_graph_backend_registry()
            assert services.retrieval_service._registry is get_retrieval_backend_registry()
            assert set(services.graph_service._factory._builders) == {"arcadedb", "neo4j"}
            assert set(services.retrieval_service._factory._builders) >= {
                "memstack_pgvector",
                "weknora_remote",
            }
    finally:
        await db.close()
        await host.close()


@pytest.mark.unit
async def test_backend_store_application_resolver_uses_the_operation_provider() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=8,
        version=8,
    )
    assert publication.accepted is True
    db = AsyncSession()
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="backend-store-application:tenant-a",
                scope=ScopeV2(kind=ScopeKindV2.TENANT, tenant_id="tenant-a"),
            ) as operation,
        ):
            _ = operation.provide(OPERATION_DB_SESSION_SERVICE_V2, db)
            resolver = operation.require(BACKEND_STORE_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, BackendStoreApplicationResolverV2)

            services = resolver.resolve(operation)

            assert getattr(services.graph_service._repo, "_session", None) is db
            assert getattr(services.retrieval_service._repo, "_session", None) is db
    finally:
        await db.close()
        await host.close()


@pytest.mark.unit
async def test_backend_store_application_rejects_missing_provider_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == BACKEND_STORE_PROVIDER_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=9)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-backend-store-services" in str(error.value)


@pytest.mark.unit
def test_backend_store_modules_are_explicit_ordered_profile_entries() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert BACKEND_STORE_PROVIDER_MODULE_V2 in enabled_modules
    assert BACKEND_STORE_APPLICATION_MODULE_V2 in enabled_modules
    provider_index = enabled_modules.index(BACKEND_STORE_PROVIDER_MODULE_V2)
    assert provider_index < enabled_modules.index(BACKEND_STORE_APPLICATION_MODULE_V2)
