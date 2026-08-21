"""Retirement gates for Web/DI-owned sandbox runtime singletons."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.configuration.containers.infra_container import InfraContainer
from src.infrastructure.adapters.primary.web.routers.sandbox import utils as sandbox_utils
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter
from src.infrastructure.plugins.v2.boundary import pin_generation_v2
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


async def test_web_and_di_projections_resolve_the_pinned_generation() -> None:
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
            assert InfraContainer().sandbox_adapter() is adapter
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
