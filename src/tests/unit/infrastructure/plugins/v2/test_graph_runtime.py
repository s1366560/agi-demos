"""Generation-owned graph runtime activation and last-good coverage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.domain.llm_providers.models import NoActiveProviderError
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.graph_runtime import (
    GRAPH_RUNTIME_SERVICE_V2,
    GraphRuntimeServiceV2,
)
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"
_ROOT_SCOPE = ScopeV2(kind=ScopeKindV2.ROOT)


class _FakeGraphService:
    def __init__(self) -> None:
        self.close_calls = 0

    async def close(self) -> None:
        self.close_calls += 1


def _runtime(host: PlatformPluginRuntimeHostV2) -> GraphRuntimeServiceV2:
    generation = host.manager.current
    assert generation is not None
    runtime = generation.resolve(GRAPH_RUNTIME_SERVICE_V2, _ROOT_SCOPE)
    assert isinstance(runtime, GraphRuntimeServiceV2)
    return runtime


async def test_graph_runtime_effect_owns_service_and_disposes_it() -> None:
    graph_service = _FakeGraphService()

    async def factory() -> Any:
        return graph_service

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(graph_runtime_factory=factory)
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
    assert runtime.graph_service is graph_service
    assert runtime.unavailable_code is None

    await host.close()

    assert graph_service.close_calls == 1


async def test_graph_runtime_failed_candidate_retains_last_good_service() -> None:
    graph_service = _FakeGraphService()
    calls = 0

    async def factory() -> Any:
        nonlocal calls
        calls += 1
        if calls == 1:
            return graph_service
        raise RuntimeError("candidate graph unavailable")

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(graph_runtime_factory=factory)
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
    assert _runtime(host).graph_service is graph_service
    assert graph_service.close_calls == 0

    await host.close()

    assert graph_service.close_calls == 1


@pytest.mark.parametrize(
    ("factory_kind", "unavailable_code"),
    (
        ("missing", "graph_runtime_factory_unavailable"),
        ("no-active-provider", "no_active_provider"),
    ),
)
async def test_optional_graph_runtime_publishes_explicit_unavailable_state(
    factory_kind: str,
    unavailable_code: str,
) -> None:
    factory = None if factory_kind == "missing" else _raise_no_active_provider
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(graph_runtime_factory=factory)
    )
    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=1,
        version=1,
    )

    assert publication.accepted is True
    runtime = _runtime(host)
    assert runtime.available is False
    assert runtime.graph_service is None
    assert runtime.unavailable_code == unavailable_code

    await host.close()


async def _raise_no_active_provider() -> Any:
    raise NoActiveProviderError
