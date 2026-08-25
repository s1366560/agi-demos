"""V2 process lifecycle coverage for the Docker event monitor."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.plugins.v2 import docker_monitor_runtime as runtime_module
from src.infrastructure.plugins.v2.artifact_content_gc_runtime import (
    ARTIFACT_CONTENT_GC_MODULE_V2,
    ASYNC_SESSION_FACTORY_MODULE_V2,
)
from src.infrastructure.plugins.v2.artifact_content_services import (
    ARTIFACT_CONTENT_APPLICATION_MODULE_V2,
)
from src.infrastructure.plugins.v2.artifact_lifecycle_services import (
    ARTIFACT_LIFECYCLE_APPLICATION_MODULE_V2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.composer import compose_profile_v2, load_profile_document_v2
from src.infrastructure.plugins.v2.docker_monitor_runtime import (
    DOCKER_EVENT_MONITOR_MODULE_V2,
    DOCKER_EVENT_MONITOR_SANDBOX_INJECT_V2,
    DOCKER_EVENT_MONITOR_SERVICE_V2,
    DOCKER_EVENT_MONITOR_SESSIONS_INJECT_V2,
    DockerEventMonitorRuntimeV2,
)
from src.infrastructure.plugins.v2.protocol import parse_plugin_manifest_v2
from src.infrastructure.plugins.v2.runtime import LoaderV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2
from src.infrastructure.plugins.v2.tenant_agent_config_services import (
    TENANT_AGENT_CONFIG_APPLICATION_MODULE_V2,
    TENANT_AGENT_CONFIG_PROVIDER_MODULE_V2,
)

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]
_PROFILE_PATH = _ROOT / "config/plugin-profiles/memstack-default.v2.yaml"
_MANIFEST_PATH = _ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json"


@pytest.fixture(autouse=True)
def _clear_docker_monitor_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SANDBOX_DOCKER_SERVICES_ENABLED", raising=False)


async def test_docker_monitor_starts_once_across_generation_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor = object()
    start = AsyncMock(return_value=monitor)
    stop = AsyncMock()
    monkeypatch.setattr(runtime_module, "start_docker_event_monitor", start)
    monkeypatch.setattr(runtime_module, "stop_docker_event_monitor", stop)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=131,
        version=131,
    )
    assert first.accepted is True
    first_generation = host.manager.current
    assert first_generation is not None
    runtime = first_generation.resolve(
        DOCKER_EVENT_MONITOR_SERVICE_V2,
        first_generation.snapshot.entries[0].scope,
    )
    assert isinstance(runtime, DockerEventMonitorRuntimeV2)
    assert runtime.monitor is monitor

    second = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=132,
        version=132,
    )

    assert second.accepted is True
    second_generation = host.manager.current
    assert second_generation is not None
    assert (
        second_generation.resolve(
            DOCKER_EVENT_MONITOR_SERVICE_V2,
            second_generation.snapshot.entries[0].scope,
        )
        is runtime
    )
    start.assert_awaited_once()
    stop.assert_not_awaited()

    await host.close()
    stop.assert_awaited_once_with()


async def test_docker_monitor_start_failure_nacks_and_cleans_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = AsyncMock(side_effect=RuntimeError("docker events unavailable"))
    stop = AsyncMock()
    monkeypatch.setattr(runtime_module, "start_docker_event_monitor", start)
    monkeypatch.setattr(runtime_module, "stop_docker_event_monitor", stop)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=133,
        version=133,
    )

    assert publication.accepted is False
    assert publication.receipt.error_code == "staging_failed"
    assert host.manager.current is None
    start.assert_awaited_once()
    stop.assert_awaited_once_with()


async def test_docker_monitor_environment_override_can_disable_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = AsyncMock()
    stop = AsyncMock()
    monkeypatch.setenv("SANDBOX_DOCKER_SERVICES_ENABLED", "false")
    monkeypatch.setattr(runtime_module, "start_docker_event_monitor", start)
    monkeypatch.setattr(runtime_module, "stop_docker_event_monitor", stop)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())

    publication = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=134,
        version=134,
    )

    assert publication.accepted is True
    start.assert_not_awaited()
    await host.close()
    stop.assert_not_awaited()


async def test_docker_monitor_config_change_requires_process_restart(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start = AsyncMock(return_value=object())
    stop = AsyncMock()
    monkeypatch.setattr(runtime_module, "start_docker_event_monitor", start)
    monkeypatch.setattr(runtime_module, "stop_docker_event_monitor", stop)
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    first = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=136,
        version=136,
    )
    assert first.accepted is True

    def disable_monitor(document):
        return replace(
            document,
            entries=tuple(
                replace(entry, config={**entry.config, "enabled": False})
                if entry.module_ref == DOCKER_EVENT_MONITOR_MODULE_V2
                else entry
                for entry in document.entries
            ),
        )

    rejected = await host.bootstrap(
        profile_path=_PROFILE_PATH,
        manifest_paths=(_MANIFEST_PATH,),
        generation=137,
        version=137,
        profile_projector=disable_monitor,
    )

    assert rejected.accepted is False
    assert rejected.receipt.error_code == "process_boundary_required"
    assert host.manager.current is not None
    assert host.manager.current.descriptor.generation == 136
    start.assert_awaited_once()
    stop.assert_not_awaited()
    await host.close()
    stop.assert_awaited_once_with()


async def test_docker_monitor_rejects_missing_sessions_without_fallback() -> None:
    document = load_profile_document_v2(_PROFILE_PATH)
    disabled = replace(
        document,
        entries=tuple(
            replace(entry, enabled=False)
            if entry.module_ref
            in {
                ARTIFACT_CONTENT_APPLICATION_MODULE_V2,
                ARTIFACT_CONTENT_GC_MODULE_V2,
                ARTIFACT_LIFECYCLE_APPLICATION_MODULE_V2,
                ASYNC_SESSION_FACTORY_MODULE_V2,
                TENANT_AGENT_CONFIG_APPLICATION_MODULE_V2,
                TENANT_AGENT_CONFIG_PROVIDER_MODULE_V2,
            }
            else entry
            for entry in document.entries
        ),
    )
    manifest = parse_plugin_manifest_v2(json.loads(_MANIFEST_PATH.read_text(encoding="utf-8")))
    snapshot = compose_profile_v2(disabled, {manifest.plugin_id: manifest}, generation=135)

    with pytest.raises(RuntimeV2Error) as error:
        await LoaderV2(builtin_runtime_definitions_v2()).stage(snapshot)

    assert error.value.code == "missing_inject_provider"
    assert "builtin-docker-event-monitor" in str(error.value)


def test_docker_monitor_contract_and_retirement_are_explicit() -> None:
    profile = load_profile_document_v2(_PROFILE_PATH)
    entry = next(
        item for item in profile.entries if item.module_ref == DOCKER_EVENT_MONITOR_MODULE_V2
    )
    main_source = (_ROOT / "src/infrastructure/adapters/primary/web/main.py").read_text(
        encoding="utf-8"
    )
    startup_exports = (
        _ROOT / "src/infrastructure/adapters/primary/web/startup/__init__.py"
    ).read_text(encoding="utf-8")
    retired_startup = _ROOT / "src/infrastructure/adapters/primary/web/startup/docker.py"

    assert entry.inject == {
        DOCKER_EVENT_MONITOR_SANDBOX_INJECT_V2: "service:application.sandbox-services",
        DOCKER_EVENT_MONITOR_SESSIONS_INJECT_V2: "service:persistence.async-session-factory",
    }
    assert entry.restart_policy.value == "process-boundary"
    assert "initialize_docker_services" not in main_source
    assert "shutdown_docker_services" not in main_source
    assert "initialize_docker_services" not in startup_exports
    assert "shutdown_docker_services" not in startup_exports
    assert not retired_startup.exists()
