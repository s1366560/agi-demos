"""V2 Provider/Consumer coverage for graph application composition."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.ports.services.graph_store_port import GraphStorePort
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.graph_application_services import (
    GRAPH_APPLICATION_MODULE_V2,
    GRAPH_APPLICATION_SERVICE_V2,
    GraphApplicationResolverV2,
)
from src.infrastructure.plugins.v2.graph_runtime import GRAPH_RUNTIME_MODULE_V2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, OperationContextV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def test_graph_resolver_uses_generation_owned_runtime() -> None:
    graph_store = cast(GraphStorePort, object())

    async def graph_factory() -> GraphStorePort:
        return graph_store

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(graph_runtime_factory=graph_factory)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=51,
        version=51,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="graph-application:project-a",
                scope=ScopeV2(
                    kind=ScopeKindV2.PROJECT,
                    tenant_id="tenant-a",
                    project_id="project-a",
                ),
            ) as operation,
        ):
            resolver = operation.require(GRAPH_APPLICATION_SERVICE_V2)

            assert isinstance(resolver, GraphApplicationResolverV2)
            services = resolver.resolve(operation)
            assert services.graph_store is graph_store
            assert services.available is True
    finally:
        await host.close()


async def test_graph_resolver_preserves_explicit_unavailable_state() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=52,
        version=52,
    )
    assert publication.accepted is True
    try:
        async with (
            await host.acquire() as generation,
            OperationContextV2(
                generation=generation,
                operation_id="graph-application:no-runtime",
                scope=ScopeV2(kind=ScopeKindV2.ROOT),
            ) as operation,
        ):
            resolver = operation.require(GRAPH_APPLICATION_SERVICE_V2)
            assert isinstance(resolver, GraphApplicationResolverV2)

            services = resolver.resolve(operation)
            assert services.available is False
            assert services.graph_store is None
            assert services.unavailable_code == "graph_runtime_factory_unavailable"
    finally:
        await host.close()


async def test_graph_module_rejects_missing_runtime_inject_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False) if entry.module_ref == GRAPH_RUNTIME_MODULE_V2 else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=53)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-graph-services" in str(error.value)
    assert "service:graph.runtime@1.0.0" in str(error.value)


def test_graph_module_is_an_explicit_ordered_profile_entry() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_entries = tuple(entry for entry in document.entries if entry.enabled)
    enabled_modules = tuple(entry.module_ref for entry in enabled_entries)

    assert GRAPH_APPLICATION_MODULE_V2 in enabled_modules
    graph_entry = next(
        entry for entry in enabled_entries if entry.module_ref == GRAPH_APPLICATION_MODULE_V2
    )
    assert graph_entry.inject == {"graph_runtime": "service:graph.runtime"}
    assert enabled_modules.index(GRAPH_RUNTIME_MODULE_V2) < enabled_modules.index(
        GRAPH_APPLICATION_MODULE_V2
    )
