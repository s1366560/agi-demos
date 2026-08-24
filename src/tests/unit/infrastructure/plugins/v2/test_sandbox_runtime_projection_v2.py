"""Retirement gates for Web/DI-owned sandbox runtime singletons."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from typing import Any

import pytest

import src.application.services.sandbox_status_sync_service as status_sync_module
import src.infrastructure.adapters.primary.web.startup.docker as docker_startup_module
import src.infrastructure.adapters.secondary.sandbox.docker_event_monitor as docker_monitor_module
from src.configuration.containers.agent_container import AgentContainer
from src.configuration.containers.infra_container import InfraContainer
from src.configuration.containers.sandbox_container import SandboxContainer
from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.primary.web.routers.sandbox import utils as sandbox_utils
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter
from src.infrastructure.plugins.v2.boundary import (
    clear_process_generation_host_v2,
    install_process_generation_host_v2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[6]


class _TrackedSandboxAdapter(MCPSandboxAdapter):
    def __init__(self) -> None:
        self.sync_calls = 0
        self.close_calls = 0

    async def sync_from_docker(self) -> int:
        self.sync_calls += 1
        return 0

    async def close(self) -> None:
        self.close_calls += 1


async def test_web_projection_resolves_the_pinned_generation() -> None:
    adapter = _TrackedSandboxAdapter()
    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(sandbox_runtime_factory=lambda: adapter)
    )
    publication = await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=76,
        version=76,
    )
    assert publication.accepted is True
    try:
        async with pin_generation_v2(host):
            assert sandbox_utils.get_sandbox_adapter() is adapter
            assert sandbox_utils.get_sandbox_orchestrator()._adapter is adapter
    finally:
        await host.close()


def test_web_sandbox_singleton_state_and_manual_shutdown_are_removed() -> None:
    assert "_sandbox_adapter" not in vars(sandbox_utils)
    assert "_sandbox_orchestrator" not in vars(sandbox_utils)
    assert "_worker_id" not in vars(sandbox_utils)
    assert "_sync_pending" not in vars(sandbox_utils)
    assert "ensure_sandbox_sync" not in vars(sandbox_utils)
    assert "shutdown_sandbox_adapter_singleton" not in vars(sandbox_utils)


def test_static_sandbox_root_facades_and_callback_injection_are_removed() -> None:
    assert "sandbox_adapter" not in vars(InfraContainer)
    assert "sandbox_event_publisher" not in vars(InfraContainer)
    assert "sandbox_adapter" not in vars(DIContainer)
    assert "sandbox_event_publisher" not in vars(DIContainer)
    assert "sandbox_adapter_factory" not in signature(SandboxContainer).parameters
    assert "sandbox_event_publisher_factory" not in signature(SandboxContainer).parameters
    assert "sandbox_orchestrator_factory" not in signature(AgentContainer).parameters
    assert "sandbox_event_publisher_factory" not in signature(AgentContainer).parameters


def test_lifespan_defers_sandbox_runtime_cleanup_to_generation_effects() -> None:
    main_source = (_ROOT / "src/infrastructure/adapters/primary/web/main.py").read_text(
        encoding="utf-8"
    )
    docker_source = (_ROOT / "src/infrastructure/adapters/primary/web/startup/docker.py").read_text(
        encoding="utf-8"
    )

    assert "shutdown_sandbox_adapter_singleton" not in main_source
    assert "_sandbox_adapter_instance" not in main_source
    assert "initialize_sandbox_idle_reaper" not in main_source
    assert "shutdown_sandbox_idle_reaper" not in main_source
    assert "ensure_sandbox_sync" not in docker_source


async def test_docker_monitor_resolves_event_publisher_for_each_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapters = [_TrackedSandboxAdapter(), _TrackedSandboxAdapter()]
    publishers: list[object] = []
    callbacks: list[Any] = []
    monitor = object()

    def sandbox_runtime_factory() -> _TrackedSandboxAdapter:
        return adapters[len(publishers)]

    class TrackedStatusSyncService:
        def __init__(self, *, repository_factory: object, event_publisher: object) -> None:
            _ = repository_factory
            publishers.append(event_publisher)

        async def handle_status_change(self, *_args: object) -> bool:
            return True

    async def start_monitor(*, on_status_change: Any) -> object:
        callbacks.append(on_status_change)
        return monitor

    monkeypatch.setenv("SANDBOX_DOCKER_SERVICES_ENABLED", "true")
    monkeypatch.setattr(status_sync_module, "SandboxStatusSyncService", TrackedStatusSyncService)
    monkeypatch.setattr(docker_monitor_module, "start_docker_event_monitor", start_monitor)

    host = PlatformPluginRuntimeHostV2(
        builtin_runtime_definitions_v2(sandbox_runtime_factory=sandbox_runtime_factory)
    )
    first = await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=77,
        version=77,
    )
    assert first.accepted is True
    install_process_generation_host_v2(host)

    try:
        assert await docker_startup_module.initialize_docker_services() is monitor
        callback = callbacks.pop()
        assert await callback("project-1", "sandbox-1", "running", "start") is True

        second = await host.bootstrap(
            profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
            manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
            generation=78,
            version=78,
        )
        assert second.accepted is True
        assert await callback("project-1", "sandbox-1", "stopped", "stop") is True

        assert len(publishers) == 2
        assert publishers[0] is not publishers[1]
    finally:
        docker_startup_module._docker_event_monitor = None
        clear_process_generation_host_v2(host)
        await host.close()
