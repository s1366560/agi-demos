"""V2 Provider/Consumer coverage for enhanced-search application composition."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.ports.services.graph_store_port import GraphStorePort
from src.domain.ports.services.retrieval_store_port import RetrievalStorePort
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.retrieval_runtime import RETRIEVAL_RUNTIME_MODULE_V2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.search_services import (
    SEARCH_APPLICATION_MODULE_V2,
    SEARCH_APPLICATION_SERVICE_V2,
    SearchApplicationResolverV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_search_resolver_uses_generation_owned_graph_and_retrieval_runtimes() -> None:
    graph_service = cast(GraphStorePort, object())
    retrieval_store = cast(RetrievalStorePort, object())

    async def graph_factory() -> GraphStorePort:
        return graph_service

    async def retrieval_factory(_graph_runtime: object) -> RetrievalStorePort:
        return retrieval_store

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(
            graph_runtime_factory=graph_factory,
            retrieval_runtime_factory=retrieval_factory,
        )
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=31,
        version=31,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="search-application:project-a",
                scope=ScopeV2(
                    kind=ScopeKindV2.PROJECT,
                    tenant_id="tenant-a",
                    project_id="project-a",
                ),
            ) as operation,
        ):
            resolver = operation.require(SEARCH_APPLICATION_SERVICE_V2)

            assert isinstance(resolver, SearchApplicationResolverV2)
            services = resolver.resolve(operation)
            assert services.graph_service is graph_service
            assert services.retrieval_store is retrieval_store
    finally:
        await host.close()


async def test_search_resolver_preserves_explicit_optional_retrieval_state() -> None:
    graph_service = cast(GraphStorePort, object())

    async def graph_factory() -> GraphStorePort:
        return graph_service

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(graph_runtime_factory=graph_factory)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=32,
        version=32,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="search-application:no-retrieval",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            resolver = operation.require(SEARCH_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, SearchApplicationResolverV2)

            services = resolver.resolve(operation)
            assert services.graph_service is graph_service
            assert services.retrieval_runtime.available is False
            assert services.retrieval_store is None
    finally:
        await host.close()


async def test_search_module_rejects_missing_retrieval_inject_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref == RETRIEVAL_RUNTIME_MODULE_V2
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=33)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-search-services" in str(error.value)
    assert "service:retrieval.env-runtime@1.0.0" in str(error.value)


async def test_search_resolver_propagates_unavailable_graph_without_fallback() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=34,
        version=34,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="search-application:no-graph",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            resolver = operation.require(SEARCH_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, SearchApplicationResolverV2)

            with pytest.raises(RuntimeV2Error) as error:
                resolver.resolve(operation)

            assert error.value.code == "graph_runtime_factory_unavailable"
    finally:
        await host.close()


def test_search_module_is_an_explicit_ordered_profile_entry() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_entries = tuple(entry for entry in document.entries if entry.enabled)
    enabled_modules = tuple(entry.module_ref for entry in enabled_entries)

    assert SEARCH_APPLICATION_MODULE_V2 in enabled_modules
    search_entry = next(
        entry for entry in enabled_entries if entry.module_ref == SEARCH_APPLICATION_MODULE_V2
    )
    assert search_entry.inject == {
        "graph_runtime": "service:graph.runtime",
        "retrieval_runtime": "service:retrieval.env-runtime",
    }
    assert enabled_modules.index(RETRIEVAL_RUNTIME_MODULE_V2) < enabled_modules.index(
        SEARCH_APPLICATION_MODULE_V2
    )
