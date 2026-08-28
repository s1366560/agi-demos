"""Generation-owned env retrieval runtime activation and retirement coverage."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.agent_worker_runtime import AGENT_WORKER_RUNTIME_MODULE_V2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.graph_application_services import GRAPH_APPLICATION_MODULE_V2
from src.infrastructure.plugins.v2.graph_runtime import GraphRuntimeServiceV2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.retrieval_runtime import (
    RETRIEVAL_RUNTIME_MODULE_V2,
    RETRIEVAL_RUNTIME_SERVICE_V2,
    RetrievalRuntimeServiceV2,
)
from src.infrastructure.plugins.v2.runtime import LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_ROOT_SCOPE = ScopeV2(kind=ScopeKindV2.ROOT)


class _FakeGraphService:
    def __init__(self, generation: int, events: list[str]) -> None:
        self.generation = generation
        self.embedder = object()
        self._events = events

    async def close(self) -> None:
        self._events.append(f"graph-close:{self.generation}")


class _FakeRetrievalStore:
    def __init__(self, generation: int, events: list[str]) -> None:
        self.generation = generation
        self._events = events

    async def close(self) -> None:
        self._events.append(f"retrieval-close:{self.generation}")


def _runtime(host: PlatformPluginRuntimeHostV2) -> RetrievalRuntimeServiceV2:
    generation = host.manager.current
    assert generation is not None
    runtime = generation.resolve(RETRIEVAL_RUNTIME_SERVICE_V2, _ROOT_SCOPE)
    assert isinstance(runtime, RetrievalRuntimeServiceV2)
    return runtime


async def test_retrieval_runtime_effect_uses_graph_inject_and_disposes_before_graph() -> None:
    events: list[str] = []
    graph_service = _FakeGraphService(1, events)
    retrieval_store = _FakeRetrievalStore(1, events)

    async def graph_factory() -> Any:
        return graph_service

    async def retrieval_factory(graph_runtime: GraphRuntimeServiceV2) -> Any:
        assert graph_runtime.graph_service is graph_service
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
        generation=1,
        version=1,
    )

    assert publication.accepted is True
    runtime = _runtime(host)
    assert runtime.available is True
    assert runtime.retrieval_store is retrieval_store
    assert runtime.unavailable_code is None

    await host.close()

    assert events == ["retrieval-close:1", "graph-close:1"]


async def test_retrieval_runtime_failed_candidate_retains_last_good_store() -> None:
    events: list[str] = []
    graph_calls = 0
    retrieval_calls = 0
    first_store = _FakeRetrievalStore(1, events)

    async def graph_factory() -> Any:
        nonlocal graph_calls
        graph_calls += 1
        return _FakeGraphService(graph_calls, events)

    async def retrieval_factory(_graph_runtime: GraphRuntimeServiceV2) -> Any:
        nonlocal retrieval_calls
        retrieval_calls += 1
        if retrieval_calls == 1:
            return first_store
        raise RuntimeError("candidate retrieval unavailable")

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(
            graph_runtime_factory=graph_factory,
            retrieval_runtime_factory=retrieval_factory,
        )
    )
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
    )
    failed = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=2,
        version=2,
    )

    assert first.accepted is True
    assert failed.accepted is False
    assert _runtime(host).retrieval_store is first_store
    assert events == ["graph-close:2"]

    await host.close()

    assert events == ["graph-close:2", "retrieval-close:1", "graph-close:1"]


async def test_optional_retrieval_runtime_publishes_explicit_unavailable_state() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
    )

    assert publication.accepted is True
    runtime = _runtime(host)
    assert runtime.available is False
    assert runtime.retrieval_store is None
    assert runtime.unavailable_code == "retrieval_runtime_factory_unavailable"

    await host.close()


async def test_retrieval_runtime_rejects_missing_graph_inject_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref
            in {
                "builtin://memstack/graph/runtime",
                AGENT_WORKER_RUNTIME_MODULE_V2,
                GRAPH_APPLICATION_MODULE_V2,
            }
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=3)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-env-retrieval-runtime" in str(error.value)
    assert "service:graph.runtime@1.0.0" in str(error.value)


def test_retrieval_runtime_is_explicitly_ordered_after_graph() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    enabled_modules = tuple(entry.module_ref for entry in document.entries if entry.enabled)

    assert RETRIEVAL_RUNTIME_MODULE_V2 in enabled_modules
    assert enabled_modules.index("builtin://memstack/graph/runtime") < enabled_modules.index(
        RETRIEVAL_RUNTIME_MODULE_V2
    )


def test_production_retrieval_runtime_has_no_process_global_registry_fallback() -> None:
    main_source = (_ROOT / "src/infrastructure/adapters/primary/web/main.py").read_text(
        encoding="utf-8"
    )
    dependency_source = (
        _ROOT / "src/infrastructure/adapters/primary/web/dependencies/__init__.py"
    ).read_text(encoding="utf-8")

    assert "register_env_default_retrieval_store" not in main_source
    assert "app.state.retrieval_store" not in main_source
    assert "retrieval_runtime_factory=retrieval_runtime_factory" in main_source
    assert "get_env_default_retrieval_store" not in dependency_source
    assert "RETRIEVAL_RUNTIME_SERVICE_V2" in dependency_source
