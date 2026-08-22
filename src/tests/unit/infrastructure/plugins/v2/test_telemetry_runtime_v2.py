"""Generation-owned telemetry lifecycle and production composition gates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.graph_runtime import GraphRuntimeFactoryV2
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2
from src.infrastructure.plugins.v2.telemetry_runtime import (
    TELEMETRY_RUNTIME_MODULE_V2,
    TELEMETRY_RUNTIME_SERVICE_V2,
    TelemetryRuntimeManagerV2,
    TelemetryRuntimeServiceV2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


async def _stage(
    manager: TelemetryRuntimeManagerV2 | None,
    *,
    generation: int,
    graph_runtime_factory: GraphRuntimeFactoryV2 | None = None,
):
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(
        load_profile_document_v2(_PROFILE_PATH),
        {manifest.plugin_id: manifest},
        generation=generation,
    )
    return await LoaderV2(
        builtin_runtime_definitions_v2(
            graph_runtime_factory=graph_runtime_factory,
            telemetry_runtime_manager=manager,
        )
    ).stage(snapshot)


async def test_overlapping_generations_share_one_telemetry_lifecycle() -> None:
    start = AsyncMock(return_value=True)
    stop = AsyncMock()
    manager = TelemetryRuntimeManagerV2(start=start, stop=stop)

    first = await _stage(manager, generation=1)
    second = await _stage(manager, generation=2)

    first_service = first.resolve(
        TELEMETRY_RUNTIME_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    second_service = second.resolve(
        TELEMETRY_RUNTIME_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    assert isinstance(first_service, TelemetryRuntimeServiceV2)
    assert isinstance(second_service, TelemetryRuntimeServiceV2)
    assert first_service.initialized is True
    assert second_service.initialized is True
    assert manager.lease_count == 2
    start.assert_awaited_once_with()

    await first.dispose()
    assert manager.lease_count == 1
    stop.assert_not_awaited()

    await second.dispose()
    assert manager.lease_count == 0
    stop.assert_awaited_once_with()


async def test_missing_data_plane_manager_is_explicitly_unavailable() -> None:
    generation = await _stage(None, generation=1)

    service = generation.resolve(
        TELEMETRY_RUNTIME_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )

    assert isinstance(service, TelemetryRuntimeServiceV2)
    assert service.initialized is False
    assert service.unavailable_code == "telemetry_runtime_manager_unavailable"
    await generation.dispose()


async def test_fastapi_runtime_activates_and_disposes_telemetry_effect() -> None:
    start = AsyncMock(return_value=True)
    stop = AsyncMock()
    manager = TelemetryRuntimeManagerV2(start=start, stop=stop)
    app = FastAPI()

    host = await initialize_plugin_runtime_v2(
        app,
        telemetry_runtime_manager=manager,
    )

    generation = host.manager.current
    assert generation is not None
    service = generation.resolve(
        TELEMETRY_RUNTIME_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    assert isinstance(service, TelemetryRuntimeServiceV2)
    assert service.initialized is True
    start.assert_awaited_once_with()

    await shutdown_plugin_runtime_v2(app)
    stop.assert_awaited_once_with()


async def test_failed_start_does_not_leak_a_manager_lease() -> None:
    start = AsyncMock(side_effect=RuntimeError("telemetry unavailable"))
    stop = AsyncMock()
    manager = TelemetryRuntimeManagerV2(start=start, stop=stop)

    with pytest.raises(RuntimeError, match="telemetry unavailable"):
        await _stage(manager, generation=1)

    assert manager.lease_count == 0
    stop.assert_not_awaited()


async def test_later_candidate_failure_releases_telemetry_effect() -> None:
    start = AsyncMock(return_value=True)
    stop = AsyncMock()
    manager = TelemetryRuntimeManagerV2(start=start, stop=stop)

    async def graph_factory() -> object:
        raise RuntimeError("graph candidate failed")

    with pytest.raises(RuntimeError, match="graph candidate failed"):
        await _stage(
            manager,
            generation=1,
            graph_runtime_factory=cast("GraphRuntimeFactoryV2", graph_factory),
        )

    assert manager.lease_count == 0
    start.assert_awaited_once_with()
    stop.assert_awaited_once_with()


def test_telemetry_is_an_explicit_process_boundary_module() -> None:
    profile = load_profile_document_v2(_PROFILE_PATH)
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))

    entry = next(item for item in profile.entries if item.module_ref == TELEMETRY_RUNTIME_MODULE_V2)
    assert entry.enabled is True
    assert entry.restart_policy.value == "process-boundary"
    assert TELEMETRY_RUNTIME_MODULE_V2 in {module.module_ref for module in manifest.modules}
    assert TELEMETRY_RUNTIME_MODULE_V2 in {
        definition.module_ref for definition in builtin_runtime_definitions_v2()
    }


def test_fastapi_lifespan_delegates_telemetry_to_v2_effect() -> None:
    source = (_ROOT / "src/infrastructure/adapters/primary/web/main.py").read_text(encoding="utf-8")

    assert "await initialize_telemetry()" not in source
    assert "shutdown_telemetry_services()" not in source
    assert "telemetry_runtime_manager=telemetry_runtime_manager" in source
